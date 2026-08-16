# Artemis MCP Foundation and Memory Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the governed MCP foundation and the first independently runnable Artemis server, `artemis-memory`, with PostgreSQL/Neon canonical writes and retryable Obsidian/vector projections.

**Architecture:** Artemis City's Python services remain the source of truth. A small common MCP package supplies strict request models, service-principal authentication, ATP/capability authorization, and SDK error translation. The memory server adapts a transport-independent `MemoryService`; PostgreSQL commits the immutable version and projection outbox before any Obsidian or vector side effect.

**Tech Stack:** Python 3.12, MCP Python SDK 2.0, Pydantic 2, psycopg2, PostgreSQL/Neon, pytest, pytest-asyncio, Hatchling, uv

**Spec:** `docs/superpowers/specs/2026-08-16-artemis-mcp-backend-servers-design.md`

## Global Constraints

- Production logic is owned by `src/`; server packages are transport adapters.
- The MCP framework is the installed official `mcp==2.0.0` `MCPServer`, not the separate `fastmcp` beta package.
- stdio owns stdout; all application diagnostics use stderr or the repository logger.
- Streamable HTTP is served only at `/mcp` and fails closed without a configured bearer verifier.
- Authentication, strict ATP validation, capability authorization, and required provenance run before a state change.
- Caller-provided fields cannot expand policy-owned capabilities.
- Pydantic boundary models use `extra="forbid"`.
- SQL is canonical. SQL failure causes no projection; projection failure leaves a durable retryable outbox event.
- Existing user changes in the `dev` worktree are preserved. Do not reset, clean, mass-format, or commit them.
- New code follows `docs/CODING_STANDARDS.md`; Black's 88-character line length is authoritative.
- Tests use literal, independently derived expectations and exercise real domain objects. External PostgreSQL and filesystem calls are isolated at their ports.

---

### Task 1: Lock the corrected routing blend contract

**Files:**
- Modify: `src/tests/test_hebbian_router.py`

**Interfaces:**
- Consumes: `HebbianRouter.route(task) -> RoutingDecision`.
- Produces: a literal regression check proving the alpha-only blend is convex.

- [ ] **Step 1: Add the exact numeric characterization test**

  Add a test with one eligible agent, composite `0.5`, scoped Hebbian weight
  `1.0`, `alpha=0.3`, and `beta=0.0`:

  ```python
  @pytest.mark.unit
  def test_hebbian_router_alpha_blend_uses_one_minus_alpha():
      registry = FakeRegistry([_Agent("A", ["research"])], {"A": 0.5})
      hebbian = FakeHebbian(scoped_weights={("A", "research"): 1.0})
      decision = HebbianRouter(registry, hebbian, alpha=0.3).route(
          {"required_capability": "research"}
      )

      assert decision.candidates[0].blended == pytest.approx(0.65)
  ```

- [ ] **Step 2: Run the characterization test**

  Run:

  ```bash
  .venv/bin/python -m pytest \
    src/tests/test_hebbian_router.py::test_hebbian_router_alpha_blend_uses_one_minus_alpha -q
  ```

  Expected: PASS against the current convex implementation. If it fails with
  `0.95`, stop before server work because the canonical router contradicts the
  design.

- [ ] **Step 3: Run the complete routing test file**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_hebbian_router.py -q
  ```

  Expected: all existing routing tests and the new literal check pass.

---

### Task 2: Add the independently buildable common MCP package

**Files:**
- Create: `services/mcp/common/pyproject.toml`
- Create: `services/mcp/common/src/artemis_mcp_common/__init__.py`
- Create: `services/mcp/common/src/artemis_mcp_common/models.py`
- Create: `services/mcp/common/tests/test_models.py`

**Interfaces:**
- Consumes: Pydantic 2 and Artemis City's Python 3.12 runtime.
- Produces: `StrictInput`, `AtpEnvelope`, `ServicePrincipal`, and `GovernedContext`.

- [ ] **Step 1: Write failing strict-model tests**

  Add tests proving unknown fields are rejected and capabilities are normalized:

  ```python
  import pytest
  from pydantic import ValidationError

  from artemis_mcp_common.models import AtpEnvelope, ServicePrincipal


  def test_atp_envelope_rejects_authority_alias():
      with pytest.raises(ValidationError, match="parent_id"):
          AtpEnvelope(
              mode="Commit",
              context="Store the reviewed note",
              action_type="Execute",
              target_zone="memory/reviewed",
              parent_provenance_id="prov-root",
              parent_id="shadow-root",
          )


  def test_service_principal_normalizes_capabilities():
      principal = ServicePrincipal(
          principal_id="operator",
          capabilities={" memory:write ", "memory:read"},
      )

      assert principal.capabilities == {"memory:read", "memory:write"}
  ```

- [ ] **Step 2: Run the tests and verify RED**

  Run:

  ```bash
  PYTHONPATH=services/mcp/common/src .venv/bin/python -m pytest \
    services/mcp/common/tests/test_models.py -q
  ```

  Expected: collection fails because `artemis_mcp_common.models` does not exist.

- [ ] **Step 3: Add package metadata**

  Create a Hatchling package named `artemis-mcp-common`, version `0.1.0`,
  requiring Python `>=3.12,<3.13`, `mcp[cli]==2.0.0`, and `pydantic>=2.4`.
  Configure pytest to collect `tests/` and expose no console script.

- [ ] **Step 4: Implement the strict models**

  Define the public shapes:

  ```python
  from __future__ import annotations

  from datetime import datetime
  from typing import Literal

  from pydantic import BaseModel, ConfigDict, Field, field_validator


  class StrictInput(BaseModel):
      model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


  class AtpEnvelope(StrictInput):
      mode: str = Field(min_length=1)
      context: str = Field(min_length=1)
      action_type: str = Field(min_length=1)
      target_zone: str = Field(min_length=1)
      parent_provenance_id: str = Field(min_length=1)


  class ServicePrincipal(StrictInput):
      principal_id: str = Field(min_length=1)
      capabilities: set[str]
      transport: Literal["stdio", "http"] = "stdio"

      @field_validator("capabilities")
      @classmethod
      def normalize_capabilities(cls, values: set[str]) -> set[str]:
          normalized = {value.strip() for value in values if value.strip()}
          if not normalized:
              raise ValueError("at least one capability is required")
          return normalized


  class GovernedContext(StrictInput):
      principal: ServicePrincipal
      atp: AtpEnvelope
      capability: str
      accepted_at: datetime
  ```

- [ ] **Step 5: Run the model tests and verify GREEN**

  Run the Step 2 command. Expected: both tests pass.

- [ ] **Step 6: Inspect package build metadata**

  Run:

  ```bash
  cd services/mcp/common && ../../../.venv/bin/python -m build --wheel
  ```

  Expected: one `artemis_mcp_common-0.1.0-*.whl` is produced; do not add `dist/`
  to Git.

---

### Task 3: Implement fail-closed principals and the ATP capability gate

**Files:**
- Create: `services/mcp/common/src/artemis_mcp_common/principals.py`
- Create: `services/mcp/common/src/artemis_mcp_common/gate.py`
- Create: `services/mcp/common/tests/test_gate.py`
- Modify: `services/mcp/common/src/artemis_mcp_common/__init__.py`
- Modify: `src/agents/atp/atp_validator.py`
- Modify: `src/tests/test_atp_validator.py`

**Interfaces:**
- Consumes: `AtpEnvelope`, `ServicePrincipal`, canonical `ATPMessage`, and `ATPValidator(strict=True)`.
- Produces: `LocalPrincipalProvider.current()`, `BearerPrincipalProvider.current()`, `StaticBearerTokenVerifier.verify_token()`, and `GovernedGate.authorize()`.

- [ ] **Step 1: Write failing authorization tests**

  Test four observable breaks: missing local principal configuration, an
  incomplete ATP envelope, an inconsistent strict Mode/ActionType pair, and a
  principal without `memory:write`:

  ```python
  import pytest

  from artemis_mcp_common.gate import GovernedGate, GovernanceDenied
  from artemis_mcp_common.models import AtpEnvelope, ServicePrincipal
  from artemis_mcp_common.principals import LocalPrincipalProvider


  def test_local_principal_fails_closed_without_identity(monkeypatch):
      monkeypatch.delenv("ARTEMIS_MCP_PRINCIPAL_ID", raising=False)
      monkeypatch.delenv("ARTEMIS_MCP_CAPABILITIES", raising=False)

      with pytest.raises(GovernanceDenied, match="principal configuration"):
          LocalPrincipalProvider.from_environment().current()


  def test_gate_rejects_unauthorized_capability():
      principal = ServicePrincipal(
          principal_id="reader",
          capabilities={"memory:read"},
      )
      envelope = AtpEnvelope(
          mode="Commit",
          context="Store reviewed memory",
          action_type="Execute",
          target_zone="memory/reviewed",
          parent_provenance_id="prov-root",
      )

      with pytest.raises(GovernanceDenied, match="memory:write"):
          GovernedGate().authorize(principal, envelope, "memory:write")
  ```

  In `src/tests/test_atp_validator.py`, add a literal strict-validation case
  using `Mode=Commit` and `ActionType=Reflect`. Assert `is_valid` is false and
  the errors identify the inconsistent pair. The equivalent non-strict case
  remains a suggestion for backwards-compatible advisory usage.

- [ ] **Step 2: Run the gate tests and verify RED**

  Run:

  ```bash
  PYTHONPATH=services/mcp/common/src:. .venv/bin/python -m pytest \
    services/mcp/common/tests/test_gate.py -q
  ```

  Expected: import failure because the principal and gate modules do not exist.

- [ ] **Step 3: Implement principal providers**

  `LocalPrincipalProvider.from_environment()` reads
  `ARTEMIS_MCP_PRINCIPAL_ID` and the comma-separated
  `ARTEMIS_MCP_CAPABILITIES`. `current()` raises `GovernanceDenied` when either
  value is absent or normalizes to only whitespace. `BearerPrincipalProvider.current()`
  reads the SDK auth context through `get_access_token()`, strips `subject` and
  every token scope, and maps the normalized values to a `ServicePrincipal`;
  no token, blank subject, or empty normalized scope set returns a controlled
  `GovernanceDenied`, never a leaked Pydantic validation failure.

  `StaticBearerTokenVerifier` stores only the configured expected token and
  uses `secrets.compare_digest`. Its `verify_token()` implementation is async,
  matching MCP SDK 2.0's `TokenVerifier` protocol. A match returns
  `AccessToken` with the presented token, configured client ID, subject, and
  scopes; a mismatch returns `None`.

- [ ] **Step 4: Implement strict ATP and capability authorization**

  Change `ATPValidator._validate_mode_action_consistency()` so an inconsistent
  pair calls `add_error()` in strict mode and retains `add_suggestion()` in
  advisory mode. Build `ATPMessage` directly from the envelope's enum values,
  use the envelope context as non-empty content, validate it using
  `ATPValidator(strict=True)`, and reject unknown enum values or any validation
  error. `GovernedGate.authorize()` must check capability membership after ATP
  validation and return:

  ```python
  GovernedContext(
      principal=principal,
      atp=envelope,
      capability=required_capability,
      accepted_at=datetime.now(timezone.utc),
  )
  ```

  The required capability is a server-owned argument. It is never accepted
  from the tool payload.

- [ ] **Step 5: Run gate tests and verify GREEN**

  Run the Step 2 command. Expected: all gate tests pass.

- [ ] **Step 6: Add bearer-verifier tests**

  Await the verifier and assert a wrong token returns `None`, a correct token
  returns the configured client ID, subject, and scopes, and the raw token is
  absent from sanitized failure text. Do not assert that the SDK
  `AccessToken.token` field is absent: the auth middleware requires it, and it
  must instead be excluded from application logs, receipts, and errors. Run
  the complete common package tests. Include whitespace-only local identity,
  bearer subject, and bearer scope cases and assert each fails with
  `GovernanceDenied`.

---

### Task 4: Define the canonical memory domain and write service

**Files:**
- Create: `src/memory/models.py`
- Create: `src/memory/ports.py`
- Create: `src/memory/service.py`
- Create: `src/tests/test_memory_service.py`
- Modify: `src/memory/__init__.py`

**Interfaces:**
- Consumes: a `MemoryLedger` and zero or more `MemoryProjection` ports.
- Produces: `MemoryWriteCommand`, `MemoryRecord`, `LedgerState`, `ProjectionState`,
  `ClaimDisposition`, `LedgerWrite`, `ProjectionClaim`, `MemoryWriteReceipt`,
  memory exceptions, and `MemoryService`.

- [ ] **Step 1: Write the SQL-failure ordering test**

  Use a recording ledger that raises from `write_version()` and real recording
  projection objects. Assert the exception propagates and no projection was
  called:

  ```python
  def test_memory_service_sql_failure_prevents_all_projection_writes():
      ledger = FailingLedger()
      obsidian = RecordingProjection("obsidian")
      vector = RecordingProjection("vector")
      service = MemoryService(ledger, [obsidian, vector])

      with pytest.raises(MemoryLedgerUnavailable):
          service.write(valid_command())

      assert obsidian.records == []
      assert vector.records == []
  ```

- [ ] **Step 2: Write the projection-failure durability test**

  Configure a real in-memory ledger test double and an Obsidian projection that
  raises. Assert the ledger retains one version, the receipt reports ledger
  `succeeded` and Obsidian `failed`, and one retryable outbox event remains.

- [ ] **Step 3: Write the idempotent replay test**

  Call `service.write()` twice with the same namespace and idempotency key.
  Assert both receipts contain the same `memory_id`, version, content hash, and
  child completion-provenance ID; the ledger contains one version and one
  completion-provenance event.

- [ ] **Step 4: Write the stale-replay protection test**

  Stage version 1 and make its Obsidian projection fail. Stage and successfully
  project version 2 for the same namespace/key/path. Replay version 1 by its
  idempotency key. Assert the ledger claim reports version 1 as superseded,
  records `skipped`, never invokes the projection adapter for version 1, and
  leaves the projected version-2 content unchanged.

  Add a same-idempotency concurrent-replay test. Two callers may observe the
  same durable record, but after the ledger locks and rereads the outbox event,
  exactly one claim has `deliver`; the other sees `terminal`. Assert exactly one
  projection-adapter call.

- [ ] **Step 5: Run the five tests and verify RED**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_memory_service.py -q
  ```

  Expected: collection fails because the memory domain modules do not exist.

- [ ] **Step 6: Implement immutable models and ports**

  Define string enums `LedgerState` (`succeeded`), `ProjectionState`
  (`pending`, `succeeded`, `failed`, `skipped`), and `WriteDisposition`
  (`created`, `replayed`), plus `ClaimDisposition` (`deliver`, `superseded`,
  `terminal`). A ledger failure raises and therefore never produces a
  successful receipt. Define frozen
  dataclasses for commands and records. `MemoryWriteCommand` contains
  namespace, key, content, metadata, idempotency key, principal ID, parent
  provenance ID, requested projections, and an optional exact
  `projection_path`. When `projection_path` is absent, derive the MCP default
  `Memory/{namespace}/{key}.md` (do not duplicate an existing `.md` suffix);
  reject POSIX absolute paths, Windows drive/UNC paths, empty/`.`/`..`
  components, and backslash traversal in namespace, key, and explicit paths.
  When `projection_path` is present, preserve that validated vault-relative
  path byte-for-byte for compatibility callers.

  `MemoryRecord` contains immutable `record_id` (this version), logical
  `memory_id` (shared by versions), namespace, key, projection path, version,
  content, content SHA-256, metadata, idempotency key, principal ID, parent
  provenance ID, child completion-provenance ID, and timezone-aware creation
  time. Historical rows may have nullable principal, parent, and child
  provenance fields; new governed writes require and return all three. Never
  use logical `memory_id` to identify a version-specific outbox event.

  Frozen dataclasses must not retain mutable caller aliases. Recursively copy
  and freeze JSON-compatible metadata (nested mappings/sequences/scalars), requested
  projections, projection-state maps, and event-ID maps at construction; expose
  immutable mapping/collection types. Tests mutate both the original inputs and
  nested returned values and prove command, record, ledger write, and receipt
  evidence cannot change. Reject `set`, `frozenset`, non-string mapping keys,
  and other non-JSON values with a controlled validation error; accepted
  metadata must round-trip through a deliberate public JSON conversion helper
  and strict `json.dumps(..., allow_nan=False)` without adapter-specific
  guessing. Reject non-finite floats at any nesting depth. Validate evidence-map
  keys as non-empty projection strings and values as real `ProjectionState` or
  non-empty event-ID strings before immutable snapshotting; runtime annotations
  alone are not validation.

  `LedgerWrite` contains the durable `MemoryRecord`, `WriteDisposition`, fixed
  `ledger_state=LedgerState.SUCCEEDED`, a `dict[str, ProjectionState]`
  loaded from the outbox, and the corresponding projection event IDs.
  `MemoryWriteReceipt` contains the record, disposition, ledger state,
  projection states, and `summary`. Define specific exceptions
  `MemoryLedgerUnavailable`, `MemoryIdempotencyConflict`, and
  `MemoryNamespaceConflict`, and `MemoryValidationError`.

  Define a context-managed `ProjectionClaim`. A claim exposes the durable
  record, target, and `ClaimDisposition`, plus
  `mark_succeeded()`, `mark_failed(error_code)`, and `mark_skipped()` methods.
  The ledger implementation must keep its per-logical-key serialization lock
  until the claim context exits; a check performed before entering the context
  is not sufficient. The ledger owns locking and classification; the service
  owns every state transition.

  Define these protocols:

  ```python
  class MemoryLedger(Protocol):
      def write_version(self, command: MemoryWriteCommand) -> LedgerWrite: ...
      def claim_projection(
          self, record_id: str, projection: str
      ) -> ContextManager[ProjectionClaim]: ...
      def read(self, namespace: str, key: str) -> MemoryRecord | None: ...
      def search(self, namespace: str, query: str, limit: int) -> list[MemoryRecord]: ...
      def projection_status(
          self, namespace: str, record_id: str
      ) -> dict[str, ProjectionState]: ...


  class MemoryProjection(Protocol):
      name: str

      def project(self, record: MemoryRecord) -> None: ...
  ```

- [ ] **Step 7: Implement `MemoryService.write()`**

  Validate namespace/key/path and require every requested projection name to
  have a configured adapter before any ledger call; unknown projections raise
  `MemoryValidationError` with no side effect. Then call
  `ledger.write_version()` exactly once before iterating projections.
  For each requested projection whose outbox state is `pending` or `failed`,
  enter `ledger.claim_projection()`. The ledger acquires its advisory lock,
  rereads the event, and returns `deliver` only if the event is still
  pending/failed and the record is the current head. For `superseded`, the
  service calls `mark_skipped()` without invoking the adapter. For `terminal`,
  it does nothing. Only for `deliver` does it call `project()` while the claim
  is held, then mark `succeeded`; on a projection exception, mark `failed` with
  a sanitized stable reason. This permits only one adapter call under
  concurrent replay and prevents an older retry racing a newer head. A crash
  after an external overwrite but before acknowledgement remains an
  at-least-once deterministic replay, not a false exactly-once claim. Return
  the ledger-owned durable IDs, `ledger_state`, and final projection states.
  Never delete a ledger record during compensation.

- [ ] **Step 8: Run the service tests and verify GREEN**

  Run the Step 5 command. Expected: all five tests pass.

- [ ] **Step 9: Add read/search boundary tests**

  Assert namespace is always passed to the ledger, search limit must be between
  1 and 100, and a missing exact memory returns `None` rather than silently
  reading another namespace.

---

### Task 5: Evolve the existing PostgreSQL/Neon ledger safely

**Files:**
- Add preserved prerequisite: `db/migrations/0001_memory_write_through.sql`
- Create: `src/memory/backends/__init__.py`
- Create: `src/memory/backends/postgres.py`
- Modify: `src/integration/sql_memory_store.py`
- Modify: `src/tests/test_sql_memory_store.py`
- Create: `db/migrations/0002_memory_server_contract.sql`
- Create: `src/tests/test_postgres_memory_ledger.py`

**Interfaces:**
- Consumes: the existing provider-neutral `0001_memory_write_through.sql`,
  `PostgresMemoryStore`, a psycopg2 connection factory, and
  `MemoryWriteCommand`.
- Produces: a backwards-compatible enhanced `PostgresMemoryStore` plus a thin
  `PostgresMemoryLedger` implementing the Task 4 port.

The existing `artemis.memory_records`, `memory_heads`, and `memory_outbox`
tables are authoritative prerequisites. Do not create replacement tables with
the same names and do not hide incompatible schemas behind
`CREATE TABLE IF NOT EXISTS`. The reviewed `0001` file is currently an
uncommitted prerequisite from the earlier write-through slice; include it
unchanged in this task's explicit commit so `0002` is never published alone.

- [ ] **Step 1: Write a transaction-order contract test**

  Extend the existing stateful DB-API fake. Assert one transaction inserts the
  immutable record, advances the head, inserts one event for every requested
  projection, and commits once when the connection context exits. Configure a
  failure on the head or outbox statement and assert the entire transaction
  rolls back with no partial record, head, or event.

- [ ] **Step 2: Write an idempotency conflict test**

  Simulate the unique `(namespace, idempotency_key)` lookup. Assert matching
  namespace, path, projection set, and content returns `replayed`; changed
  content/path/projection set raises `MemoryIdempotencyConflict` without
  changing the original record. A key reused in another namespace is allowed.

- [ ] **Step 3: Write a serialized stale-claim test**

  Create version 1, then version 2 for the same logical key. Claim version 1's
  pending event. Assert the store takes the same namespace/key advisory lock
  used by `stage_write()`, rereads the outbox event and locked current head,
  and yields `ClaimDisposition.SUPERSEDED` without changing state. Assert the
  service-owned `mark_skipped()` transition persists under that lock. Assert a
  current pending/failed event yields `DELIVER`, a succeeded/skipped event
  yields `TERMINAL`, and a current claim remains held until its context exits.

- [ ] **Step 4: Run the adapter tests and verify RED**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_postgres_memory_ledger.py -q
  ```

  Expected: import failure because `PostgresMemoryLedger` does not exist.

- [ ] **Step 5: Add a versioned evolution migration**

  `0002_memory_server_contract.sql` must evolve, never replace, the existing
  provider-neutral `0001` schema. In a transaction it:

  - adds `namespace`, `memory_key`, `principal_id`,
    `parent_provenance_id`, and requested-projection evidence to records;
  - verifies and temporarily disables only the expected
    `memory_records_immutable` trigger, backfills only newly added context
    columns, re-enables the trigger in the same transaction, and verifies the
    original immutable columns did not change;
  - backfills existing rows as namespace `legacy` with
    `memory_key=relative_path`, while leaving principal, parent provenance, and
    absent completion provenance nullable rather than fabricating historical
    claims;
  - adds/backfills namespace and key columns on heads and a unique logical-key
    constraint;
  - replaces the global idempotency uniqueness constraint with
    `(namespace, idempotency_key)` after the backfill;
  - expands the existing outbox target constraint from only `obsidian` to
    `obsidian` and `vector`;
  - maps existing statuses exactly as `pending -> pending`,
    `processing -> pending`, `delivered -> succeeded`, and `dead -> skipped`
    before installing the public state constraint
    `pending|succeeded|failed|skipped`;
  - adds a `memory_completion_provenance` table keyed by `record_id`, with a
    unique child `provenance_id`, parent provenance ID, principal ID, event type
    `memory.write`, and timestamp; new writes insert it transactionally while
    migrated rows without evidence remain absent; the existing
    `memory_records.provenance_id` column stores that same child ID for new
    writes; and
  - retains the original relative path, record IDs, memory IDs, revisions, and
    pending Obsidian events.

  Before mutation, preflight every retained legacy path against the domain's
  exact compatibility path rules. `0001` permits some shapes (including
  internal backslashes) that the strict `MemoryRecord` contract rejects. Fail
  the migration with actionable offending-row evidence rather than silently
  normalize immutable paths or create rows the application cannot read.

  Use explicit constraint names and fail visibly when the expected `0001`
  schema is absent or unexpectedly shaped. Do not use `IF NOT EXISTS` to mask
  an incompatible table or column. Add a migration test that applies `0001`,
  inserts populated record/head/outbox rows in every legacy status, applies
  `0002`, and proves immutable content/hashes/IDs are unchanged with the trigger
  active again.

- [ ] **Step 6: Implement the enhanced store and adapter**

  Enhance `PostgresMemoryStore` without breaking its existing imports. New
  writes accept namespace/key, principal/provenance evidence, exact
  `relative_path`, and requested projection targets. Execute all record, head,
  completion-provenance, and outbox statements in one transaction, then commit
  once; roll back the whole transaction on any error. Generate the child
  completion-provenance UUID exactly once in that transaction; replay returns
  the same child ID. Before allocating a revision, take a
  transaction-scoped advisory lock derived from namespace/key and lock/read the
  current head.

  Preserve the existing global relative-path binding. A migrated path is
  authoritatively `namespace="legacy"`, `key=relative_path`. A new write must
  reject a projection path already bound to a different namespace/key with a
  typed `MemoryNamespaceConflict` before attempting an insert. The same legacy
  identity increments the existing logical memory instead of producing a raw
  primary-key failure.

  Implement a context-managed projection claim using that same advisory lock.
  Keep the transaction and lock open across the adapter side effect. After the
  lock is acquired, reread the outbox event. Classify succeeded/skipped as
  `terminal`, a non-current record as `superseded`, and only a current
  pending/failed event as `deliver`; do not transition it until the service
  calls the corresponding claim method. Implement exact read,
  namespace-scoped text search, and namespace-plus-record-ID projection-status
  queries.
  `PostgresMemoryLedger` only maps between Task 4 domain objects and this store;
  it does not issue a second independent set of SQL statements. Do not run DDL
  from constructors or server startup.

  Preserve the legacy `stage_write()` API by implementing it as the explicit
  `namespace="legacy"`, `key=relative_path`, Obsidian-only compatibility adapter
  over the canonical write path. Do not retain a second SQL implementation:
  the old outbox insert omits the required `0001` status and its `delivered`
  state is invalid after `0002`. Map canonical `succeeded` back to the legacy
  receipt surface only where compatibility requires it.

  Serialize all callers sharing `(namespace, idempotency_key)`, even when their
  logical paths differ, or resolve a 23505 loser by reading the committed
  namespace-scoped winner and applying the same replay/conflict checks. Replay
  fails closed unless durable outbox event IDs/status keys exactly equal the
  recorded requested-projection set and the governed completion-provenance row
  matches the record's child ID.

  Make version-specific status preserve existence: return `None` for a missing
  or cross-namespace record and `{}` only for an existing record with zero
  projections. Carry this distinction through the provider-neutral ledger port
  so the MCP boundary never guesses or performs an unrelated second lookup.

- [ ] **Step 7: Run adapter tests and verify GREEN**

  Run the Step 4 command plus `src/tests/test_sql_memory_store.py`. Expected:
  all old and new store contracts pass.

- [ ] **Step 8: Run optional real-PostgreSQL integration test**

  When `ARTEMIS_TEST_DATABASE_URL` is set, require a separate explicit
  destructive-test opt-in plus `ARTEMIS_TEST_DATABASE_EXPECTED_HOST` and
  `ARTEMIS_TEST_DATABASE_EXPECTED_NAME`. Parse the DSN without connecting,
  require its normalized host/database identity to equal those explicit
  expected values, and reject normalized identity equality with
  `ARTEMIS_MEMORY_DATABASE_URL` even when the two URLs use different textual
  spellings or credentials. Do not log any DSN or identity value. Complete all
  checks before any connection, `DROP SCHEMA`, or DDL.
  Apply the migration to that disposable database starting from `0001`, then
  `0002`; write two versions through the real adapter, replay one
  idempotency key, prove replay returns the same completion-provenance ID, prove
  a stale event is skipped, exercise an upgraded populated legacy path, and
  verify record/head/completion/outbox state through SQL. Skip with an explicit
  reason when the variable or explicit opt-in is absent; never point this test
  at `ARTEMIS_MEMORY_DATABASE_URL`. Do not rely on an outer connection context
  to undo migration files that contain their own transaction boundaries.

---

### Task 6: Add Obsidian and vector projection adapters

**Files:**
- Add preserved prerequisite: `src/obsidian_integration/manager.py`
- Add preserved prerequisite: `src/tests/test_obsidian_projection.py`
- Create: `src/memory/backends/obsidian.py`
- Create: `src/memory/backends/vector.py`
- Create: `src/tests/test_memory_projections.py`

**Interfaces:**
- Consumes: `ObsidianManager`, vector store `upsert`, and `MemoryRecord`.
- Produces: `ObsidianMemoryProjection` and `VectorMemoryProjection`.

The crash-safe `ObsidianManager` overwrite work is a reviewed working-tree
prerequisite from the earlier write-through slice. Include its implementation
and focused tests in this task's explicit commit so the adapter is not shipped
without the durable replacement behavior it relies on.

- [ ] **Step 1: Write path-containment and payload tests**

  Assert an MCP command without an override derives namespace `reviewed` and
  key `daily/brief` as a vault-relative path under `Memory/reviewed/`. Assert a
  compatibility record carrying `Agent Outputs/sample.md` preserves that exact
  path. Traversal and absolute paths are rejected. The vector document ID is
  the durable logical `memory_id`. Assert metadata includes namespace, key,
  version, content hash, both `path` and `projection_path` set to the exact
  projection path, and provenance ID.

  Extend the preserved filesystem tests before implementation. On POSIX,
  simulate swapping a validated parent path to an outward symlink and prove the
  held descriptor-relative operation cannot escape the vault. Assert exact
  UTF-8 bytes (no newline translation), and assert a post-replacement directory
  sync error does not attempt to unlink any reappearing temp pathname. On
  Windows, assert this POSIX durability adapter fails as unsupported before any
  file, directory, or replacement side effect.

- [ ] **Step 2: Run projection tests and verify RED**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_memory_projections.py -q
  ```

  Expected: import failure because the adapters do not exist.

- [ ] **Step 3: Implement Obsidian projection**

  Use the already-derived `record.projection_path`; do not recompute it from
  namespace/key inside the adapter. Validate every component with
  `PurePosixPath`, reject absolute paths, `.` and `..`, and call
  `ObsidianManager.write_note()` once. Render frontmatter containing the durable
  identifiers followed by the exact content. Path serialization must remain
  compatible with existing caller-supplied vault-relative paths.

  Harden the prerequisite `ObsidianManager` overwrite implementation on POSIX:
  open the vault and traverse/create parent components with descriptor-relative
  operations and `O_NOFOLLOW`; hold the validated parent directory descriptor
  through exclusive temp creation, binary UTF-8 write, file fsync,
  descriptor-relative `os.replace`, and parent fsync. Reject an existing target
  symlink. Cleanup the exact temp entry only before replacement; never unlink a
  path after `replacement_applied=True`. Preserve existing target mode and
  process umask behavior. The first implementation is explicitly POSIX-only;
  on Windows, fail before any mutation until a separately reviewed Win32
  write-through implementation exists.

- [ ] **Step 4: Implement vector projection**

  Call `vector_store.upsert(str(record.memory_id), record.content, metadata)`.
  Do not delete prior vector documents during an Obsidian failure; SQL/outbox
  status controls repair.

- [ ] **Step 5: Run projection and legacy memory tests**

  Run:

  ```bash
  .venv/bin/python -m pytest \
    src/tests/test_memory_projections.py \
    src/tests/test_memory_bus.py \
    src/tests/test_memory_bus_integration.py \
    src/tests/integration/test_memory_bus_integration.py -q
  ```

  Expected: new projection tests pass and the existing bus baseline is unchanged.

---

### Task 7: Build the `artemis-memory` MCP server package

**Files:**
- Modify: `services/mcp/common/src/artemis_mcp_common/models.py`
- Modify: `services/mcp/common/src/artemis_mcp_common/gate.py`
- Modify: `services/mcp/common/tests/test_gate.py`
- Create: `services/mcp/artemis-memory/pyproject.toml`
- Create: `services/mcp/artemis-memory/src/artemis_memory_mcp/__init__.py`
- Create: `services/mcp/artemis-memory/src/artemis_memory_mcp/models.py`
- Create: `services/mcp/artemis-memory/src/artemis_memory_mcp/server.py`
- Create: `services/mcp/artemis-memory/src/artemis_memory_mcp/wiring.py`
- Create: `services/mcp/artemis-memory/src/artemis_memory_mcp/__main__.py`
- Create: `services/mcp/artemis-memory/tests/test_server_contract.py`

**Interfaces:**
- Consumes: `MemoryService`, `GovernedGate`, a transport-specific principal provider, and MCP SDK 2.0.
- Produces: `create_memory_server(..., auth=None, token_verifier=None) -> MCPServer`
  and the `artemis-memory-mcp` console command. The optional auth arguments are
  passed to the `MCPServer` constructor; handlers do not simulate transport
  authentication themselves.

- [ ] **Step 1: Write failing tool-list contract test**

  Create a real `MCPServer` with an in-memory ledger and local principal. Connect
  with the public MCP 2.0 `mcp.client.Client(server)` in-process API and assert
  the tool names are exactly:

  ```python
  {"write-memory", "read-memory", "search-memory", "get-memory-status"}
  ```

  Assert every returned Python tool model has an object `input_schema`, a
  non-empty `output_schema`, and all four annotation fields. Camel-case
  `inputSchema` and `outputSchema` are wire-serialization names, not Python
  attributes. Assert `(await client.list_resources()).resources == []`.
  MCP 2.0 still advertises the resources capability even when the listing is
  empty, so do not assert that the capability itself is absent. A resource
  read has no first-class, schema-validated ATP payload; `_meta`, input
  responses, and request state are not accepted as authority channels.

- [ ] **Step 2: Write failing structured write test**

  Call `write-memory` with a complete ATP envelope and literal content. Assert
  `is_error` is false and `structured_content` contains the logical memory ID,
  immutable record ID, version `1`, literal SHA-256,
  `ledger_state="succeeded"`, and projection states. This field must come from
  the domain receipt, not be injected as an unconditional string by the
  handler.

- [ ] **Step 3: Write failing denial test**

  Use a principal with only `memory:read`. Call `write-memory`; assert `is_error`
  is true, the error reason identifies `memory:write`, and the in-memory ledger
  remains empty.

  Add a cross-namespace case. A principal with `memory:write` and
  `memory:namespace:reviewed` may write `reviewed` but is denied for `private`;
  a `memory:namespace:*` grant may access either. Namespace grants and the
  required namespace scope are server-owned authorization evidence and never
  come from a tool-supplied capability field.

- [ ] **Step 4: Run server tests and verify RED**

  Run:

  ```bash
  PYTHONPATH=.:services/mcp/common/src:services/mcp/artemis-memory/src \
    .venv/bin/python -m pytest \
    services/mcp/artemis-memory/tests/test_server_contract.py -q
  ```

  Expected: import failure because the server package does not exist.

- [ ] **Step 5: Add package metadata and console script**

  Create `artemis-memory-mcp` version `0.1.0`, Python `>=3.12,<3.13`, with
  dependencies `artemis-city==1.0.0`, `artemis-mcp-common==0.1.0`,
  `mcp[cli]==2.0.0`, `pydantic>=2.4`, and `psycopg2-binary>=2.9`. Add uv path
  sources for Artemis City and the common package. Register:

  ```toml
  [project.scripts]
  artemis-memory-mcp = "artemis_memory_mcp.__main__:main"
  ```

- [ ] **Step 6: Implement typed MCP models**

  `WriteMemoryInput` contains namespace, key, content, metadata, idempotency key,
  requested projections, and `AtpEnvelope`; it does not contain principal,
  capability, namespace grants, trust, or routing score fields. Define
  `ReadMemoryInput(namespace, key, atp)`,
  `SearchMemoryInput(namespace, query, limit, atp)`, and
  `GetMemoryStatusInput(namespace, record_id, atp)` explicitly. Status is
  version-specific and must never accept logical `memory_id`. Read, search, and
  status inputs carry `AtpEnvelope` rather than bypassing ATP through a
  URI-only path.
  Results are typed Pydantic models with a `summary` field, required
  `ledger_state`, and exact projection-status objects.

  Lock a flat public input schema, matching the conformance examples under
  `/Users/pucci/projects/servers`: declare the public fields as tool-handler
  parameters and construct the strict input model inside the handler. A single
  `params: WriteMemoryInput` parameter would instead expose a nested
  `{ "params": ... }` wire contract and must not be introduced accidentally.

  Extend `GovernedContext` with the accepted scope and
  `GovernedGate.authorize(..., required_scope=None)`. When a scope is supplied,
  require either its exact string (for memory,
  `memory:namespace:{normalized_namespace}`) or the server-recognized
  `memory:namespace:*` grant after ATP and capability validation. Return a
  controlled `GovernanceDenied` before the service on mismatch.

- [ ] **Step 7: Register four annotated tools**

  Construct `MCPServer("artemis-memory", version="0.1.0", auth=auth,
  token_verifier=token_verifier)`. Require both auth arguments together and
  reject a partial pair. Register each tool with `structured_output=True` so an
  invalid result schema fails at registration rather than silently degrading.
  The write tool is
  destructive, idempotent, and closed-world. Read, search, and status are
  read-only, idempotent, and closed-world. Each handler:

  1. resolves the transport principal;
  2. authorizes the server-owned capability and namespace scope through
     `GovernedGate`;
  3. converts input to a domain command;
  4. offloads the synchronous service call with `anyio.to_thread.run_sync`; and
  5. returns the typed result.

  Translate `GovernanceDenied`, validation errors, ledger failures, and
  idempotency conflicts to controlled, sanitized MCP tool errors at this
  boundary. Success output schemas do not define a typed error schema: an
  ordinary controlled tool exception becomes `CallToolResult(is_error=True)`,
  while raising `MCPError` causes `Client.call_tool()` itself to raise.

- [ ] **Step 8: Prove every read surface is governed**

  Call read, search, and status through the real client. Assert each validates
  a canonical `Commit` + `Execute` ATP envelope and the server-owned read
  capability before the ledger. Missing records return a controlled not-found
  tool error, distinct from an existing record with zero projection events.
  Write two versions and prove status for version-1 `record_id` cannot
  return version-2 events. Prove a namespace in the input cannot bypass the
  principal's exact/wildcard namespace grant. Defer a browsable `memory://`
  resource until the provenance server can
  resolve a durable ATP reference from a URI without accepting authority fields
  or synthesized intent.

- [ ] **Step 9: Run server tests and verify GREEN**

  Run the Step 4 command. Expected: tool-list, structured write, denial, and
  governed read tests pass through a real client session.

---

### Task 8: Wire stdio and authenticated Streamable HTTP

**Files:**
- Modify: `services/mcp/artemis-memory/src/artemis_memory_mcp/wiring.py`
- Modify: `services/mcp/artemis-memory/src/artemis_memory_mcp/__main__.py`
- Create: `services/mcp/artemis-memory/tests/test_cli.py`
- Create: `services/mcp/artemis-memory/tests/test_http_auth.py`
- Create: `services/mcp/artemis-memory/README.md`

**Interfaces:**
- Consumes: environment configuration and `create_memory_server()`.
- Produces: stdio default and authenticated Streamable HTTP `/mcp`.

- [ ] **Step 1: Write failing configuration tests**

  Assert dependency wiring fails before opening a database connection when
  `ARTEMIS_MEMORY_DATABASE_URL` is missing. Assert stdio also requires
  `ARTEMIS_MCP_PRINCIPAL_ID` and `ARTEMIS_MCP_CAPABILITIES`. Assert `--http`
  requires `ARTEMIS_MCP_BEARER_TOKEN`, `ARTEMIS_MCP_HTTP_CLIENT_ID`,
  `ARTEMIS_MCP_HTTP_SUBJECT`, `ARTEMIS_MCP_HTTP_SCOPES`,
  `ARTEMIS_MCP_AUTH_ISSUER_URL`, and
  `ARTEMIS_MCP_RESOURCE_SERVER_URL`. The configured local capabilities or HTTP
  scopes must include the transport-wide `artemis:memory` scope, operation
  capabilities, and exact/wildcard memory namespace grants used by the tests.

- [ ] **Step 2: Run CLI tests and verify RED**

  Run:

  ```bash
  PYTHONPATH=.:services/mcp/common/src:services/mcp/artemis-memory/src \
    .venv/bin/python -m pytest services/mcp/artemis-memory/tests/test_cli.py -q
  ```

  Expected: configuration tests fail because CLI wiring is incomplete.

- [ ] **Step 3: Implement dependency wiring**

  Build a psycopg2 connection factory from `ARTEMIS_MEMORY_DATABASE_URL`, an
  `ObsidianManager` from the canonical vault setting, and the configured vector
  store through the existing vector-store factory. Do not open connections or
  run migrations at import time. If an operator explicitly selects a remote
  vector backend and it cannot be constructed, fail setup instead of silently
  substituting local SQLite; callers may omit the vector projection when they
  intentionally want SQL plus Obsidian only.

- [ ] **Step 4: Implement transport selection**

  Parse `--http`, `--host`, and `--port`. stdio creates a
  `LocalPrincipalProvider` and calls `server.run("stdio")`. HTTP creates a
  `StaticBearerTokenVerifier` plus `BearerPrincipalProvider`, builds MCP 2.0
  `AuthSettings` from the configured issuer/resource URLs and required scopes,
  and passes both `auth` and `token_verifier` into `create_memory_server()`.
  Set `AuthSettings.required_scopes` only to the global transport scope
  `['artemis:memory']` (or an equivalently reviewed single global scope).
  MCP middleware treats this list conjunctively, so operation capabilities and
  namespace grants remain in `AccessToken.scopes` for per-tool enforcement by
  `GovernedGate`; do not require every read/write/namespace grant on every HTTP
  request.
  Only that authenticated server may call:

  ```python
  server.run(
      "streamable-http",
      host=args.host,
      port=args.port,
      streamable_http_path="/mcp",
  )
  ```

  Print startup diagnostics to stderr only.

- [ ] **Step 5: Prove HTTP authentication at the ASGI boundary**

  Build the deterministic test app without opening a listener:

  ```python
  app = server.streamable_http_app(
      streamable_http_path="/mcp",
      json_response=True,
      stateless_http=True,
  )
  ```

  Enter `app.router.lifespan_context(app)` explicitly; `httpx.ASGITransport`
  does not start the SDK session-manager lifespan. Use a base URL with an
  explicit accepted host and port such as `http://127.0.0.1:8000` so the SDK's
  DNS-rebinding guard does not return 421. Through that ASGI client, assert a
  missing or wrong bearer token receives 401 before any tool/service call.
  Assert a valid configured token reaches a read handler and
  `BearerPrincipalProvider` observes the expected subject and scopes. For an
  `/mcp` resource URL, inspect
  `/.well-known/oauth-protected-resource/mcp`. No assertion, response, log
  capture, or exception text may contain the raw configured token.

- [ ] **Step 6: Document configuration and invocation**

  The README lists every variable, marks database URL and tokens as
  operator-supplied, shows stdio and HTTP commands, explains migration
  application, and documents that projection failures return a durable pending
  or failed state.

- [ ] **Step 7: Run CLI and HTTP-auth tests and verify GREEN**

  Run the Step 2 command plus `test_http_auth.py`. Expected: all configuration
  and ASGI authentication tests pass without opening a real network listener.

---

### Task 9: Introduce the compatibility adapter and run release proof

**Files:**
- Create: `src/memory/compat.py`
- Modify: `src/integration/memory_bus.py`
- Modify: `src/mcp/vector_store.py`
- Modify: `src/mcp/supabase_vector_store.py`
- Modify: `src/tests/test_memory_bus.py`
- Modify: `src/tests/test_memory_bus_integration.py`
- Modify: `src/tests/integration/test_memory_bus_integration.py`
- Modify: `docs/MEMORY_BUS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/superpowers/specs/2026-08-16-neon-obsidian-memory-write-through-design.md`

**Interfaces:**
- Consumes: `MemoryService` and a `MemoryCompatibilityContextProvider` behind
  optional constructor arguments.
- Produces: existing `MemoryBus.write_note_with_embedding()` behavior through the canonical service when configured, with a reversible legacy path during migration.

- [ ] **Step 1: Write the compatibility test first**

  Construct `MemoryBus` with a recording `MemoryService`. Call
  `write_note_with_embedding()` and assert the canonical service receives one
  command carrying the context provider's validated namespace, principal, and
  parent provenance ID; the caller's exact vault-relative path and content;
  metadata; and a stable caller-supplied or generated idempotency key. Assert
  `embed=False` requests only `obsidian`, while `embed=True` requests
  `obsidian` and `vector`. Assert the legacy vector-first method is not called.

  Add a fail-closed test: when `memory_service` is configured without a
  compatibility context provider, the call raises before SQL or projection
  side effects. Do not invent a `legacy` authenticated identity or provenance
  parent in runtime code.

  Add an upgraded-legacy-path test. A populated `0001` path is bound to
  `namespace="legacy"`, `key=relative_path`; the compatibility provider must
  return that identity so a delegated write advances the existing memory.
  Supplying a different namespace/key for the bound path raises typed
  `MemoryNamespaceConflict` before a raw primary-key error or side effect.

- [ ] **Step 2: Run the compatibility test and verify RED**

  Run the focused test node. Expected: `MemoryBus` rejects the new service
  dependency or still calls the vector store directly.

- [ ] **Step 3: Add the reversible delegation path**

  Define an immutable `MemoryCompatibilityContext` and provider protocol in
  `src/memory/compat.py`. Accept both `memory_service: MemoryService | None`
  and `compatibility_context_provider` in `MemoryBus`. When the service is
  present, require the provider, preserve `relative_path` as
  `projection_path`, derive only the logical key, and adapt `embed` to the exact
  projection set. Permit optional `idempotency_key`, `provenance_id`, and
  `source_agent` inputs without breaking existing positional callers; explicit
  provenance may refine but may not contradict the authenticated context.
  Preserve `source_agent` as non-authoritative record metadata; it never
  replaces the authenticated principal ID.

  A path already migrated by `0002` has the authoritative compatibility
  identity `namespace="legacy"`, `key=relative_path`. New paths may use the
  provider's normal namespace/key. The ledger owns the path-binding check and
  fails closed on a conflicting logical identity.

  Map the receipt back to the existing dictionary shape plus ledger/projection
  states. Preserve the legacy returned path-based `doc_id`, and add the logical
  `memory_id`/UUID vector document ID explicitly. On a delegated vector write,
  register decay under `str(record.memory_id)`, not the normalized path.
  Preserve governance-success bookkeeping after a successful delegated write.
  When the service is absent, preserve the
  current code path byte-for-byte except for extraction needed to keep function
  size within the repository standard.

  Include vector metadata `path=record.projection_path`. Extend both vector
  stores' decay-record reads to return metadata, build a durable
  path-to-logical-ID map during `_load_decay_records()`, and update it after a
  delegated write. Vector search results refresh access using the actual vector
  hit `doc_id`; exact/keyword results use the path map with the legacy
  normalized-path fallback. Add a write/read/restart test proving
  `update_decay_state()` targets the UUID. Do not automatically delete a stale
  path-keyed vector alias; report it for a separately reviewed cleanup so this
  migration is non-destructive.

- [ ] **Step 4: Run memory regressions**

  Run:

  ```bash
  .venv/bin/python -m pytest \
    src/tests/test_memory_service.py \
    src/tests/test_postgres_memory_ledger.py \
    src/tests/test_sql_memory_store.py \
    src/tests/test_memory_projections.py \
    src/tests/test_memory_bus.py \
    src/tests/test_memory_bus_integration.py \
    src/tests/integration/test_memory_bus_integration.py -q
  ```

  Expected: all new and legacy memory tests pass.

- [ ] **Step 5: Run MCP contract and package checks**

  Run:

  ```bash
  PYTHONPATH=.:services/mcp/common/src:services/mcp/artemis-memory/src \
    .venv/bin/python -m pytest \
    services/mcp/common/tests \
    services/mcp/artemis-memory/tests -q
  .venv/bin/python -m ruff check \
    src/memory services/mcp/common services/mcp/artemis-memory
  .venv/bin/python -m black --check \
    src/memory services/mcp/common services/mcp/artemis-memory
  git diff --check
  ```

  Expected: tests and formatting checks pass with no warnings or whitespace
  errors.

- [ ] **Step 6: Run the canonical Artemis regression suite**

  Run:

  ```bash
  make test
  ```

  Record pre-existing failures separately. Any failure in routing, ATP,
  provenance, memory, bridge, or packaging caused by this change is a regression
  and must be fixed before proceeding.

- [ ] **Step 7: Inspect the built server artifact**

  Build the common and memory wheels. Inspect their file lists and metadata.
  Install both into a clean temporary environment and import the entry point so
  local uv path sources are not mistaken for a distributable dependency proof.
  Confirm neither artifact contains `.env`, database files, logs, caches,
  Obsidian notes, test fixtures, or raw credentials.

- [ ] **Step 8: Update architecture documentation**

  Document SQL-first canonical memory, projection/outbox states, the governed
  MCP tool contracts and deferred-resource rationale, migration application,
  and the reversible
  `MemoryBus` delegation switch. Update the earlier Neon/Obsidian design to
  describe the additive `0002` schema evolution, vector events, and serialized
  stale-claim rule. Remove claims that a projection failure deletes the
  canonical memory record.

---

## Follow-on plans required by the umbrella design

After this plan is verified, create and execute one independently reviewable
plan for each remaining server in this order:

1. `artemis-provenance` shared-core extraction and receipt/chain parity;
2. `artemis-validation` authoritative strict ATP service;
3. `artemis-registry` and `artemis-governance` read/admin boundaries;
4. `artemis-task` canonical queue claim, retry, cancellation, and idempotency;
5. `artemis-routing` read-only preview plus attributed model/provider/route
   evidence, accelerated half-life, entropy, Sentinel, and version scoping.

The backend-server objective is not complete when only `artemis-memory` ships.
Completion requires all mapped servers, their governed pipeline, SDK contract
tests, packaging, and integration evidence described by the design spec.
