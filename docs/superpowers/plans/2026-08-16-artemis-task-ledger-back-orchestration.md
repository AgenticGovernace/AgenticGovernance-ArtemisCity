# Artemis Transactional Task Loop and Back-Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace file-note execution state with a transactional task ledger that provides atomic claims, replay-safe finalization, bounded parent/child orchestration, durable provenance, exactly-once learning, and asynchronous Obsidian projection.

**Architecture:** SQLite is the initial local/test adapter behind a `TaskLedger` port. A successful agent result is first stored with ledger state `finalizing`, then linked result provenance and the governed next state are committed without redispatch. Child graphs are validated and admitted atomically with immutable delegation grants and budget reservations; Obsidian and vector writes consume an outbox after canonical state commits.

**Tech Stack:** Python 3.12, SQLite, Pydantic 2, pytest, existing RunLogger, MemoryBus, Hebbian, registry, and trust stores

**Spec:** `docs/superpowers/specs/2026-08-16-artemis-routing-kernel-consolidation-design.md`

**Depends on:** `docs/superpowers/plans/2026-08-16-artemis-routing-kernel-core.md`

## Global Constraints

- The ledger is the only execution-state authority. Obsidian notes are readable projections, never a concurrent queue lock.
- Claims use atomic compare-and-set semantics. Two workers cannot own one task attempt.
- External submission identity is `(task_id, generation, input_sha256, submission_idempotency_key)`.
- Attempt identity is `(task_id, generation, continuation.sequence, child_result_set_sha256, attempt_idempotency_key)`.
- A `finalizing` task has a durable `OutcomeV1` and is never dispatched again.
- Missing or unknown agent result status is `invalid_agent_result`, never success.
- Outcome persistence and linked result provenance both precede terminal completion and every learning update.
- A unique `(outcome_id, learning_policy_version)` application key prevents duplicate learning in the ledger and in every mutable learning store.
- Planning, checkpoint, continuation-control, and scheduler graph-control outcomes are always learning-ineligible.
- Child effective authority is the intersection of verified requester, verified scheduler actor, persisted grant, child ATP domain, reservation, and current policy.
- Grant persistence, budget reservation, child tasks/edges, and parent `waiting_children` transition commit atomically or not at all.
- Projection failure cannot rerun a completed agent. Only the failed outbox item retries.
- New and touched code follows `docs/CODING_STANDARDS.md`; tests use disposable databases and vault roots.
- Do not duplicate or overwrite the concurrent SQL memory/outbox work in `src/integration/sql_memory_store.py`; consume it through a port after its owning change is committed.
- Preserve unrelated dirty paths and stage only the files named by each task.

---

### Task 1: Add the ledger port, schema, submission replay, and atomic claim

**Files:**

- Create: `src/tasks/__init__.py`
- Create: `src/tasks/ledger.py`
- Create: `src/tasks/sqlite_ledger.py`
- Create: `src/tests/test_task_ledger.py`

**Interfaces:**

- Consumes: `TaskEnvelopeV1` and `OutcomeV1` from the Routing Kernel core plan.
- Produces: `TaskLedger`, `TaskRecord`, `SubmissionReceipt`, `ClaimReceipt`, `LedgerConflict`, and `SQLiteTaskLedger`.

The port exposes these exact operations:

```python
class TaskLedger(Protocol):
    def submit(self, envelope: TaskEnvelopeV1) -> SubmissionReceipt:
        """Admit a new generation or replay its current durable state."""

    def get(self, task_id: str, generation: int) -> TaskRecord | None:
        """Return one durable task generation."""

    def claim_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> ClaimReceipt | None:
        """Atomically claim one pending or due retry attempt."""
```

- [ ] **Step 1: Write submission replay and conflict tests**

  Use two independent `SQLiteTaskLedger` instances against one temporary file.
  Assert same identity returns the same record; changed input under the same
  task ID/generation raises `task_input_conflict`; a terminal replay returns the
  stored outcome without a new attempt.

  ```python
  def test_same_submission_replays_current_state(ledger, root_envelope):
      first = ledger.submit(root_envelope)
      replay = ledger.submit(root_envelope)

      assert replay.disposition == "replayed"
      assert replay.task == first.task


  def test_changed_input_under_same_task_id_conflicts(ledger, root_envelope):
      ledger.submit(root_envelope)
      changed = root_envelope.model_copy(update={"input_sha256": "f" * 64})

      with pytest.raises(LedgerConflict) as conflict:
          ledger.submit(changed)
      assert conflict.value.code == "task_input_conflict"
  ```

- [ ] **Step 2: Write the two-connection claim race**

  Synchronize two threads immediately before `BEGIN IMMEDIATE`; both call
  `claim_next`. Assert exactly one receives a `ClaimReceipt`, one active attempt
  row exists, and the task's `state_version` increments once.

- [ ] **Step 3: Run the tests to verify RED**

  ```bash
  .venv/bin/python -m pytest src/tests/test_task_ledger.py -q
  ```

  Expected: collection fails because `src.tasks` does not exist.

- [ ] **Step 4: Implement the initial schema and transactional submit**

  Initialize, in one migration transaction, these tables:

  - `tasks`: primary key `(task_id, generation)`, input/submission identity,
    state, state version, continuation identity, attempt counters, active lease,
    retry time, reason, parent/root references, outcome reference, timestamps.
  - `task_attempts`: unique attempt identity and dispatch/replay-safety evidence.
  - `outcomes`: unique `outcome_id` and unique `attempt_id`, canonical JSON and
    hashes.
  - `finalization_stages`: unique `(task_id, generation, stage_key)`.
  - `projection_outbox`: unique `event_id` and idempotency key.
  - `learning_applications`: unique `(outcome_id, learning_policy_version)`.

  Enable `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, and a bounded busy
  timeout on every connection. `submit()` uses `BEGIN IMMEDIATE`; it inserts a
  new `pending` row or validates exact identity and returns the existing row.

- [ ] **Step 5: Implement atomic claim**

  In one `BEGIN IMMEDIATE` transaction, select the oldest eligible `pending` or
  due `retry_wait` row, derive the deterministic attempt identity, insert the
  attempt, and compare-and-set state/version to `running`. A `finalizing`,
  terminal, blocked, cancelled, or `waiting_children` row is never claimable.

- [ ] **Step 6: Run focused tests and commit**

  ```bash
  .venv/bin/python -m pytest src/tests/test_task_ledger.py -q
  .venv/bin/python -m black --check src/tasks src/tests/test_task_ledger.py
  git add src/tasks/__init__.py src/tasks/ledger.py src/tasks/sqlite_ledger.py \
    src/tests/test_task_ledger.py
  git commit -m "feat(tasks): add atomic SQLite task ledger"
  ```

---

### Task 2: Add lease recovery, bounded retry, and explicit requeue

**Files:**

- Modify: `src/tasks/ledger.py`
- Modify: `src/tasks/sqlite_ledger.py`
- Modify: `src/tests/test_task_ledger.py`

**Interfaces:**

- Consumes: `ClaimReceipt` from Task 1.
- Produces: `mark_dispatch_started`, `schedule_retry`, `recover_expired_leases`, and `requeue`.

```python
def mark_dispatch_started(
    self,
    claim: ClaimReceipt,
    *,
    agent_name: str,
    replay_safety: Literal["idempotent", "lookup", "unsafe"],
) -> None:
    """Persist dispatch evidence before invoking the agent."""


def recover_expired_leases(self, now: datetime) -> list[RecoveryReceipt]:
    """Recover safe leases and block uncertain external side effects."""


def schedule_retry(
    self,
    claim: ClaimReceipt,
    *,
    retry_at: datetime,
    reason_code: str,
) -> TaskRecord:
    """Move a retryable running attempt to retry_wait."""


def requeue(
    self,
    task_id: str,
    *,
    expected_generation: int,
    reason_code: str,
) -> TaskRecord:
    """Create the next explicit generation while retaining the input hash."""
```

- [ ] **Step 1: Write lease-recovery tests**

  Cover a lease that expired before dispatch, an idempotent dispatched agent, an
  authoritative result-lookup agent, and an unsafe external side effect.
  Expected states are `retry_wait`, `retry_wait`, lookup-dependent completion or
  retry, and `blocked` respectively. Assert no recovery path returns a
  `finalizing` task to execution.

- [ ] **Step 2: Write retry and requeue tests**

  Assert bounded retry preserves generation and increments the attempt identity.
  Assert explicit requeue increments generation, retains input hash, clears the
  terminal outcome reference, and rejects a stale `expected_generation`.

- [ ] **Step 3: Run focused tests to verify RED**

  ```bash
  .venv/bin/python -m pytest src/tests/test_task_ledger.py -q
  ```

- [ ] **Step 4: Implement compare-and-set transitions**

  Every transition includes `WHERE state_version=? AND state=?` and requires
  exactly one changed row. Use stable reason codes, not free-form exceptions, in
  ledger state. Recovery writes a provenance/outbox decision request but does
  not fabricate an agent result.

- [ ] **Step 5: Run tests and commit**

  ```bash
  .venv/bin/python -m pytest src/tests/test_task_ledger.py -q
  git add src/tasks/ledger.py src/tasks/sqlite_ledger.py \
    src/tests/test_task_ledger.py
  git commit -m "feat(tasks): add replay-safe lease recovery"
  ```

---

### Task 3: Persist OutcomeV1 and idempotent result provenance before completion

**Files:**

- Create: `src/provenance/__init__.py`
- Create: `src/provenance/ports.py`
- Create: `src/provenance/run_logger_adapter.py`
- Create: `src/routing/finalizer.py`
- Create: `src/tests/test_routing_finalizer.py`
- Modify: `src/utils/run_logger.py`
- Modify: `src/tests/test_run_logger_provenance.py`

**Interfaces:**

- Consumes: `OutcomeV1`, `TaskLedger`, and canonical `src.utils.run_logger.RunLogger`.
- Produces: `CompletionProvenancePort.commit_result`, `OutcomeFinalizer.finalize`, and `OutcomeFinalizer.resume`.

```python
class CompletionProvenancePort(Protocol):
    def commit_result(
        self,
        outcome: OutcomeV1,
        *,
        parent_provenance_id: str,
        stage_key: str,
    ) -> ProvenanceReceipt:
        """Idempotently persist linked result provenance."""


class OutcomeFinalizer:
    def finalize(
        self,
        *,
        envelope: TaskEnvelopeV1,
        decision: RoutingDecisionV1,
        raw_result: Mapping[str, object],
    ) -> FinalizationResult:
        """Validate, stage, and finish one admitted execution result."""

    def resume(self, task_id: str, generation: int) -> FinalizationResult:
        """Resume a durable finalizing task without redispatch."""
```

- [ ] **Step 1: Write invalid-result and ordering tests**

  Add one shared call recorder and assert:

  ```python
  assert calls == [
      "stage_outcome",
      "commit_result_provenance",
      "commit_result_state_and_outbox",
      "apply_learning_once",
  ]
  ```

  Missing or unknown `status` must construct a typed
  `invalid_agent_result` outcome with `learning_eligible=False`. Outcome-store
  failure produces no completion/provenance/learning call. Provenance failure
  leaves `finalizing` and produces no learning.

- [ ] **Step 2: Write replay tests for each finalization stage**

  Use deterministic stage key
  `outcome:{outcome_id}:result-provenance:v1`. Simulate a crash after outcome,
  after provenance, and after state/outbox. `resume()` must reuse the same
  outcome/provenance IDs and never call dispatch.

- [ ] **Step 3: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_routing_finalizer.py \
    src/tests/test_run_logger_provenance.py
  ```

- [ ] **Step 4: Add idempotent stage storage to RunLogger**

  Add a unique `stage_key` column/index to the canonical provenance table using
  an idempotent migration. `commit_result` returns the existing event when the
  same key and content hash replay; a different hash under the same key raises
  `provenance_stage_conflict`.

- [ ] **Step 5: Implement finalization order**

  `stage_outcome()` validates and atomically inserts `OutcomeV1` plus
  `running -> finalizing`. After provenance succeeds, commit the governed result
  state and projection outbox together. Only then invoke the learning
  coordinator. A learning failure records `learning_status="failed"` without
  changing the durable outcome or replaying the agent.

- [ ] **Step 6: Run focused tests and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_task_ledger.py \
    src/tests/test_routing_finalizer.py \
    src/tests/test_run_logger_provenance.py
  git add src/provenance src/routing/finalizer.py \
    src/utils/run_logger.py src/tests/test_routing_finalizer.py \
    src/tests/test_run_logger_provenance.py
  git commit -m "feat(routing): finalize outcomes before learning"
  ```

---

### Task 4: Make Hebbian, registry, and trust learning idempotent per outcome

**Files:**

- Create: `src/routing/learning.py`
- Create: `src/tests/test_learning_idempotency.py`
- Modify: `src/mcp/hebbian_weights.py`
- Modify: `src/integration/agent_registry.py`
- Modify: `src/integration/learning_governance.py`
- Modify: `src/integration/trust_interface.py`
- Modify: `src/tests/test_hebbian_learning.py`
- Modify: `src/tests/test_learning_governance.py`

**Interfaces:**

- Consumes: a durable outcome and result-provenance receipt.
- Produces: `OutcomeLearningCoordinator.apply_once(outcome, provenance) -> LearningReceipt` and idempotent store methods keyed by `(outcome_id, learning_policy_version)`.

- [ ] **Step 1: Write durability-precondition tests**

  Assert the coordinator rejects an outcome without a durable outcome reference
  or result provenance. Assert `learning_eligible=False` returns `skipped`
  without calling any mutable store.

- [ ] **Step 2: Write partial-crash replay tests**

  Inject crashes after the Hebbian write, registry execution counter, and trust
  event. Re-run the same outcome/policy version and assert no weight, decay,
  timing sample, pair bonus, execution counter, or trust counter changes twice.
  Provider unavailability, cancellation, degraded fallback, planning,
  checkpoint, and graph-control outcomes must call no mutable learning store.

- [ ] **Step 3: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_learning_idempotency.py \
    src/tests/test_hebbian_learning.py \
    src/tests/test_learning_governance.py
  ```

- [ ] **Step 4: Add one application table to every mutable store**

  Each database uses a unique primary key on `(outcome_id,
learning_policy_version)` and stores content hash, state, and timestamp. A
  repeated identical application returns its prior receipt; a hash mismatch is
  `learning_application_conflict`.

- [ ] **Step 5: Implement the coordinator**

  The coordinator marks the ledger application pending, calls each store's
  idempotent method, and records `completed` only after all required store
  receipts exist. On failure it records the failed component and supports
  governed retry with the same keys.

- [ ] **Step 6: Run focused tests and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_learning_idempotency.py \
    src/tests/test_hebbian_learning.py \
    src/tests/test_learning_governance.py
  git add src/routing/learning.py src/mcp/hebbian_weights.py \
    src/integration/agent_registry.py src/integration/learning_governance.py \
    src/integration/trust_interface.py src/tests/test_learning_idempotency.py \
    src/tests/test_hebbian_learning.py src/tests/test_learning_governance.py
  git commit -m "feat(learning): apply outcomes exactly once"
  ```

---

### Task 5: Authorize bounded child graphs and atomically fan out

**Files:**

- Modify: `src/auth/delegation.py`
- Create: `src/tasks/graph.py`
- Create: `src/tests/test_task_graph.py`
- Modify: `src/tasks/sqlite_ledger.py`
- Modify: `src/routing/contracts.py`

**Interfaces:**

- Consumes: durable parent task/outcome, `AuthorityContextV1`, strict intent resolver, Artemis authorizer, and current policy.
- Produces: `ChildTaskSpecV1`, `DelegationGrantV1`, `GraphLimits`, `AuthorizedChildPlan`, `TaskGraphService.authorize_plan`, and `SQLiteTaskLedger.accept_child_plan`.

```python
class TaskGraphService:
    def authorize_plan(
        self,
        *,
        parent: TaskRecord,
        outcome: OutcomeV1,
        children: tuple[ChildTaskSpecV1, ...],
        authority: AuthorityContextV1,
        limits: GraphLimits,
    ) -> AuthorizedChildPlan:
        """Validate graph shape and derive only narrowing grants."""


def accept_child_plan(
    self,
    plan: AuthorizedChildPlan,
    *,
    expected_state_version: int,
) -> FanOutReceipt:
    """Atomically persist the complete accepted child plan."""
```

- [ ] **Step 1: Write validation tests before schema changes**

  Cover duplicate IDs, missing dependency, self-edge, cycle, depth, fan-out,
  total-task, time, and cost limit violations. Cover child scope widening,
  expired requester/actor receipt, grant hash mismatch, and insufficient
  budget. Assert zero task/edge/grant/reservation rows exist after each denial.

- [ ] **Step 2: Write atomic fan-out failure tests**

  Inject a failure after grant insert, reservation insert, child insert, and edge
  insert. After every failure, assert no new record of any kind and the parent
  remains `finalizing`. Add replay and concurrent budget-reservation races.

- [ ] **Step 3: Run graph tests to verify RED**

  ```bash
  .venv/bin/python -m pytest src/tests/test_task_graph.py -q
  ```

- [ ] **Step 4: Implement exact child and grant models**

  `ChildTaskSpecV1` and `DelegationGrantV1` use the approved spec fields and
  strict frozen Pydantic configuration. Grant IDs, hashes, reservation IDs,
  child IDs, and edge IDs derive deterministically from root/parent/outcome plus
  the child's idempotency seed. A child envelope carries only grant ID/hash;
  the ledger loads the immutable record.

- [ ] **Step 5: Add graph tables and one fan-out transaction**

  Add `delegation_grants`, `budget_reservations`, `task_edges`, and graph-limit
  accounting tables. In one `BEGIN IMMEDIATE` transaction, insert immutable
  grants, reserve budget, create child tasks/edges, and compare-and-set the
  parent from `finalizing` to `waiting_children`. Any error rolls back all rows.

- [ ] **Step 6: Run tests and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_task_graph.py src/tests/test_task_ledger.py
  git add src/auth/delegation.py src/tasks/graph.py \
    src/tasks/sqlite_ledger.py src/routing/contracts.py \
    src/tests/test_task_graph.py
  git commit -m "feat(tasks): add bounded atomic child fan-out"
  ```

---

### Task 6: Add idempotent fan-in, continuation, failure, and cancellation policy

**Files:**

- Modify: `src/tasks/graph.py`
- Modify: `src/tasks/ledger.py`
- Modify: `src/tasks/sqlite_ledger.py`
- Modify: `src/tests/test_task_graph.py`

**Interfaces:**

- Consumes: terminal child outcomes and persisted edge policies.
- Produces: `fan_in`, `apply_child_terminal_policy`, `ContinuationReceipt`, and `ParentResolution`.

```python
def fan_in(
    self,
    parent_task_id: str,
    generation: int,
) -> ContinuationReceipt | None:
    """Create at most one continuation for the complete required child set."""


def apply_child_terminal_policy(
    self,
    child_outcome_id: str,
) -> ParentResolution:
    """Apply the persisted failure/cancellation edge policy."""
```

- [ ] **Step 1: Write continuation hashing and replay tests**

  Canonically sort required child tuples `(outcome_id, content_sha256,
failure_policy, cancellation_policy)`, encode canonical JSON, and hash it.
  Assert exactly one continuation increments sequence, keeps the same
  generation, sets the child-result hash, and derives a distinct attempt key.
  Duplicate/out-of-order child events return the prior continuation.

- [ ] **Step 2: Write failure and cancellation policy tests**

  Cover `continue-partial`, `fail-parent`, and terminal policy. Assert
  scheduler-generated parent outcomes and linked decision provenance exist for
  failure/cancellation branches and are `learning_eligible=False`.

- [ ] **Step 3: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest src/tests/test_task_graph.py -q
  ```

- [ ] **Step 4: Implement fan-in and policy transitions atomically**

  Only the ledger can move `waiting_children -> pending`. External replay cannot
  advance it. Use unique continuation identity and compare-and-set parent
  version. A `continue-partial` continuation carries an explicit typed partial
  set; other terminal policies move the parent through `finalizing` and the
  normal provenance finalizer.

- [ ] **Step 5: Run tests and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_task_graph.py src/tests/test_routing_finalizer.py
  git add src/tasks/graph.py src/tasks/ledger.py src/tasks/sqlite_ledger.py \
    src/tests/test_task_graph.py
  git commit -m "feat(tasks): add idempotent child fan-in policies"
  ```

---

### Task 7: Project durable task state to Obsidian through an outbox

**Files:**

- Create: `src/tasks/projection.py`
- Create: `src/tests/test_task_projection.py`
- Modify: `src/mcp/orchestrator.py`
- Modify after its owning change lands: `src/integration/memory_bus.py`

**Interfaces:**

- Consumes: committed `projection_outbox` events and canonical MemoryBus write port.
- Produces: `TaskProjectionWorker.run_once(limit) -> ProjectionBatchReceipt`.

- [ ] **Step 1: Write projection idempotency and retry tests**

  Assert a committed terminal state produces one outbox event. A projection
  crash leaves the event retryable, does not change the task outcome, and does
  not call an agent. Replay uses an outcome-derived idempotency key and never
  writes a second logical report.

- [ ] **Step 2: Write Obsidian status mapping tests**

  Map canonical states to readable front matter. The legacy `in progress` value
  is accepted only on ingestion and projects as `running`. Routing, ATP,
  governance, and provenance denials project as `blocked` plus a stable reason.

- [ ] **Step 3: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest src/tests/test_task_projection.py -q
  ```

- [ ] **Step 4: Implement claim/complete/fail outbox operations**

  Claim projection rows atomically with a lease. Pass the outcome-derived
  idempotency key to MemoryBus. On success mark the row complete; on failure
  store safe error code, attempts, and next retry time. The worker never imports
  agent classes or the router.

- [ ] **Step 5: Convert orchestrator note writes to projection requests**

  Keep existing Obsidian scanning/batch compatibility, but remove direct status
  writes from the execution lifecycle. Submitted notes become ledger tasks; the
  worker projects subsequent canonical state.

- [ ] **Step 6: Run tests and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_task_projection.py \
    src/tests/test_memory_bus.py \
    src/tests/test_memory_bus_integration.py
  git add src/tasks/projection.py src/tests/test_task_projection.py \
    src/mcp/orchestrator.py src/integration/memory_bus.py
  git commit -m "feat(tasks): project ledger state through outbox"
  ```

---

### Task 8: Wire the durable finalizer into the shared kernel and add reconciliation

**Files:**

- Create: `src/tasks/reconciler.py`
- Create: `src/tests/test_routing_lifecycle.py`
- Modify: `src/routing/kernel.py`
- Modify: `src/routing/finalizer.py`
- Modify: `src/mcp/orchestrator.py`
- Modify: `src/tests/test_orchestrator_coverage.py`

**Interfaces:**

- Consumes: completed ledger, graph, finalizer, learning, and projection ports.
- Produces: one real lifecycle for execute/stream and `FinalizationReconciler.run_once(limit)`.

- [ ] **Step 1: Add real temporary-store lifecycle tests**

  Use SQLite ledger and RunLogger adapters, not mocks, for both execute and
  stream. Assert the exact order:

  ```python
  assert durable_trace == [
      "authenticate",
      "validate_atp",
      "authorize_capability",
      "filter_eligibility",
      "governed_rank",
      "dispatch",
      "persist_outcome",
      "persist_completion_provenance",
      "transition_state_and_enqueue_projection",
      "learn_once",
      "complete",
  ]
  ```

  Assert equal outcome/provenance IDs for sync and stream, no learning on
  planning/graph-control outcomes, and no terminal stream event before durable
  finalization.

  Add a long-output case proving context compression is admitted as a typed
  child task through the graph/delegation path. The summarizer cannot be called
  directly, and its result follows the same auth, ATP, authorization, routing,
  outcome, provenance, and learning gates.

- [ ] **Step 2: Add finalizing reconciliation tests**

  Seed tasks stopped after each durable stage. The reconciler resumes provenance,
  result transition, projection scheduling, or learning and never invokes the
  executor. If the initial outcome/finalizing transaction never committed,
  recover according to replay-safety evidence or block for review.

- [ ] **Step 3: Run tests to verify RED**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_routing_lifecycle.py \
    src/tests/test_orchestrator_coverage.py
  ```

- [ ] **Step 4: Install the durable finalizer and reconciler**

  Replace the recording finalizer port from the core plan. Keep
  `Orchestrator.route_and_execute_task`, `assign_and_execute_task`, and
  `stream_route_and_execute` as compatibility methods that delegate once to the
  same injected Routing Kernel; remove duplicated learning/report/completion
  order from both paths.

- [ ] **Step 5: Run the task-loop proof**

  ```bash
  .venv/bin/python -m pytest -q -p no:cacheprovider \
    src/tests/test_task_ledger.py \
    src/tests/test_task_graph.py \
    src/tests/test_routing_finalizer.py \
    src/tests/test_learning_idempotency.py \
    src/tests/test_task_projection.py \
    src/tests/test_routing_lifecycle.py \
    src/tests/test_orchestrator_coverage.py \
    src/tests/test_run_logger_provenance.py \
    src/tests/test_hebbian_learning.py
  ```

  Expected: all tests pass with no live-store writes.

- [ ] **Step 6: Commit durable kernel integration**

  ```bash
  git add src/tasks/reconciler.py src/routing/kernel.py \
    src/routing/finalizer.py src/mcp/orchestrator.py \
    src/tests/test_routing_lifecycle.py \
    src/tests/test_orchestrator_coverage.py
  git commit -m "feat(tasks): reconcile durable routing finalization"
  ```
