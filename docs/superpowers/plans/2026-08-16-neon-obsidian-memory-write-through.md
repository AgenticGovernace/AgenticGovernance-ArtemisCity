# Neon and Obsidian Memory Write-Through Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Neon-compatible PostgreSQL the durable Artemis City memory
ledger and deliver Obsidian as an idempotent projection with explicit
`accepted + sync_pending` behavior.

**Architecture:** A provider-neutral PostgreSQL store commits an immutable
memory revision, current head, and Obsidian outbox event in one short
transaction. `MemoryBus` then attempts the vector and Obsidian projections;
projection failure never deletes canonical SQL. This first slice retains the
outbox evidence but retry is caller-driven with the same idempotency key; it
does not run an automatic projection worker.

**Tech Stack:** Python 3.12, psycopg2, PostgreSQL 16/Neon, pytest, pathlib,
Obsidian filesystem adapter

**Spec:**
`docs/superpowers/specs/2026-08-16-neon-obsidian-memory-write-through-design.md`

## Global Constraints

- PostgreSQL is authoritative whenever `ARTEMIS_MEMORY_BACKEND` is `postgres`
  or `neon`; explicit selection fails closed and never substitutes SQLite.
- A committed SQL revision is never deleted because a projection failed.
- Obsidian failure returns `status=accepted` and `sync_pending=true`.
- `embed=False` disables only semantic projection; it never skips canonical SQL.
- Hebbian calculations, trust learning, SEED, and embedding policy are unchanged.
- Operator database URLs, Obsidian credentials, and bearer tokens are never
  generated, logged, committed, or copied into browser assets.
- Existing unrelated changes in the dirty shared checkout are preserved.
- Do not create another worktree, commit, or push during this implementation.
- Every production behavior is preceded by a focused failing test and observed
  RED result.
- Initial rollout runs one task-executing orchestrator worker because atomic
  multi-worker task claims/leases are not part of this slice.
- Existing derived vector indexes require a one-time rebuild because canonical
  path IDs replace the older underscore-normalized IDs.

---

### Task 1: PostgreSQL memory ledger and transactional outbox

**Files:**
- Create: `db/migrations/0001_memory_write_through.sql`
- Create: `src/integration/sql_memory_store.py`
- Create: `src/tests/test_sql_memory_store.py`

**Interfaces:**
- Consumes: a psycopg2-compatible `connection_factory` returning a connection
  with context-managed transactions and cursors.
- Produces: `MemoryRevision`, `MemoryWriteReceipt`, `SqlMemoryStore`,
  `PostgresMemoryStore`, `MemoryStoreError`, and `IdempotencyConflictError`.

- [ ] **Step 1: Add the first failing transaction-contract tests**

  Add tests with a stateful fake PostgreSQL connection that exercises the real
  `PostgresMemoryStore` SQL sequence. The first tests must prove:

  ```python
  def test_stage_write_commits_revision_head_and_outbox_together(): ...
  def test_stage_write_rolls_back_all_state_when_outbox_insert_fails(): ...
  def test_replaying_idempotency_key_returns_original_receipt(): ...
  def test_reusing_idempotency_key_for_different_content_raises_conflict(): ...
  def test_get_current_returns_committed_revision_while_projection_pending(): ...
  ```

  Hand-derive expected path, revision `1`, SHA-256, and `pending` status in the
  fixtures. Do not compute expected values with production helpers.

- [ ] **Step 2: Run the new tests and observe RED**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_sql_memory_store.py -q
  ```

  Expected: collection fails because `src.integration.sql_memory_store` does
  not exist. Resolve only test syntax/import mistakes; keep the behavior RED.

- [ ] **Step 3: Add the provider-neutral migration**

  Create schema `artemis`, the `memory_records`, `memory_heads`, and
  `memory_outbox` tables from the approved design, plus:

  ```sql
  CREATE INDEX memory_outbox_pending_idx
      ON artemis.memory_outbox (status, next_attempt_at, revision)
      WHERE status IN ('pending', 'processing');
  ```

  Add checks rejecting absolute paths and any path containing a `..` segment.
  Do not enable pgvector and do not add Supabase roles or RLS policies.

- [ ] **Step 4: Implement the minimum store models and write transaction**

  Implement these public boundaries with annotations and Google-style
  docstrings:

  ```python
  class PostgresMemoryStore:
      def __init__(self, connection_factory: Callable[[], ConnectionLike]): ...

      def stage_write(
          self,
          *,
          relative_path: str,
          content: str,
          metadata: Mapping[str, object] | None,
          idempotency_key: str,
          provenance_id: str | None = None,
          source_agent: str | None = None,
      ) -> MemoryWriteReceipt: ...

      def get_current(self, relative_path: str) -> MemoryRevision | None: ...
      def mark_delivered(self, event_id: str) -> None: ...
      def mark_projection_failed(self, event_id: str, error_code: str) -> None: ...
      def list_pending(self, limit: int = 100) -> list[MemoryWriteReceipt]: ...
  ```

  `stage_write` first checks `idempotency_key`. Identical path and SHA-256
  returns the stored receipt with `duplicate=True`; any mismatch raises
  `IdempotencyConflictError`. A new write locks the current head, assigns the
  next revision, inserts all three records, and commits once.

- [ ] **Step 5: Run the store tests GREEN and refactor**

  Run the Task 1 tests, then Black and Ruff on the two Python files:

  ```bash
  .venv/bin/python -m pytest src/tests/test_sql_memory_store.py -q
  .venv/bin/python -m black --check src/integration/sql_memory_store.py src/tests/test_sql_memory_store.py
  .venv/bin/python -m ruff check --no-cache src/integration/sql_memory_store.py src/tests/test_sql_memory_store.py
  ```

  Expected: all tests pass; formatting and lint commands exit zero.

---

### Task 2: Deterministic, crash-safe Obsidian projection

**Files:**
- Modify: `src/obsidian_integration/manager.py`
- Create: `src/tests/test_obsidian_projection.py`

**Interfaces:**
- Consumes: validated vault-relative path and the exact content committed to SQL.
- Produces: retry-idempotent `write_note(relative_path, content, overwrite=True)`
  using durable same-directory replacement.

- [ ] **Step 1: Add failing filesystem behavior tests**

  Use a real `tmp_path` vault and the real `ObsidianManager`:

  ```python
  def test_concurrent_writes_use_distinct_temporary_files(tmp_path): ...
  def test_failed_replace_preserves_existing_note(tmp_path, monkeypatch): ...
  def test_retry_overwrites_with_identical_bytes(tmp_path): ...
  def test_overwrite_flushes_file_and_parent_directory(tmp_path, monkeypatch): ...
  ```

  The mutation each test catches is respectively a shared `.tmp` filename,
  truncation/deletion of the old target, non-deterministic append behavior, and
  an omitted durability flush.

- [ ] **Step 2: Run the tests and observe RED**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_obsidian_projection.py -q
  ```

  Expected: the unique-temp and durability tests fail against the shared
  `<target>.tmp` implementation.

- [ ] **Step 3: Implement durable replacement**

  Use `tempfile.NamedTemporaryFile` with `dir=full_path.parent`,
  `delete=False`, and a target-derived prefix. Write text, `flush()`,
  `os.fsync(file.fileno())`, `os.replace(temp_path, full_path)`, then open the
  parent directory read-only and `os.fsync(dir_fd)`. Cleanup only the exact
  temporary path if replacement fails. Preserve path-confinement checks and the
  existing append mode for non-projector callers.

- [ ] **Step 4: Run projection tests GREEN**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_obsidian_projection.py -q
  .venv/bin/python -m pytest src/tests/test_obsidian_manager.py -q
  ```

  If the second file is absent, run the existing tests selected by
  `-k ObsidianManager` under `src/tests` and record that substitution.

---

### Task 3: MemoryBus accepted and sync-pending state machine

**Files:**
- Modify: `src/integration/memory_bus.py`
- Modify: `src/tests/test_memory_bus.py`
- Modify: `src/tests/test_memory_bus_integration.py`

**Interfaces:**
- Consumes: optional `SqlMemoryStore` injected as `sql_store`.
- Produces: the existing memory write receipt plus canonical SQL identity and
  projection status fields.

- [ ] **Step 1: Replace unsafe rollback expectations with failing SQL-mode tests**

  Preserve legacy-mode tests and add a real in-memory stateful fake implementing
  the `SqlMemoryStore` protocol. Add these behaviors:

  ```python
  def test_sql_failure_never_touches_obsidian(): ...
  def test_obsidian_failure_keeps_sql_revision_and_returns_sync_pending(): ...
  def test_embed_false_still_commits_canonical_sql(): ...
  def test_success_marks_outbox_delivered_and_reports_synced(): ...
  def test_duplicate_write_returns_original_revision(): ...
  def test_projection_ack_failure_remains_sync_pending(): ...
  ```

  The Obsidian-failure assertion is:

  ```python
  assert result["status"] == "accepted"
  assert result["sync_pending"] is True
  assert result["sql_status"] == "committed"
  assert result["obsidian_status"] == "pending"
  ```

- [ ] **Step 2: Run the focused tests and observe RED**

  Run the six new test node IDs. Expected: construction fails because
  `MemoryBus` has no `sql_store`, or receipts lack the new status fields.

- [ ] **Step 3: Implement SQL-first behavior without breaking legacy mode**

  Add `sql_store: SqlMemoryStore | None = None` to `MemoryBus.__init__` and add
  keyword-only write inputs:

  ```python
  idempotency_key: str | None = None,
  provenance_id: str | None = None,
  source_agent: str | None = None,
  ```

  In SQL mode, validate first, stage SQL before any projection, and return
  `accepted + sync_pending` for Obsidian or delivery-ack failures. Do not call
  `vector_store.delete()` as compensation for a committed SQL revision.
  Preserve the current exception/rollback behavior only when `sql_store is
  None`, so rollout compatibility remains explicit.

- [ ] **Step 4: Make SQL the read-after-write authority in SQL mode**

  Exact-path reads consult `sql_store.get_current()` before Obsidian so a
  pending projection is immediately readable. Canonical list/stats also use
  SQL. Query search uses the optional exact SQL path and derived vector index;
  Obsidian keyword fallback is legacy-only.

- [ ] **Step 5: Run focused and existing MemoryBus tests GREEN**

  Run:

  ```bash
  .venv/bin/python -m pytest src/tests/test_memory_bus.py src/tests/test_memory_bus_integration.py -q
  ```

  Expected: legacy compatibility and the SQL-mode contract both pass.

---

### Task 4: Shared store factory and fail-closed runtime wiring

**Files:**
- Create: `src/integration/memory_store_factory.py`
- Create: `src/tests/test_memory_store_factory.py`
- Modify: `src/mcp/orchestrator.py`
- Modify: `src/api_bridge.py`
- Modify: `src/tests/test_orchestrator_coverage.py`
- Modify: `src/tests/test_api_bridge.py`

**Interfaces:**
- Consumes: `ARTEMIS_MEMORY_BACKEND` and
  `ARTEMIS_MEMORY_DATABASE_URL` from the process environment.
- Produces: `create_sql_memory_store()` used by both orchestrator and bridge.

- [ ] **Step 1: Add failing factory tests**

  Add:

  ```python
  def test_legacy_backend_returns_none(monkeypatch): ...
  def test_neon_backend_without_url_fails_closed(monkeypatch): ...
  def test_neon_connection_failure_never_returns_sqlite(monkeypatch): ...
  def test_postgres_backend_builds_store_with_short_connection_factory(monkeypatch): ...
  ```

  Assert stable reason code `MEMORY_DATABASE_CONFIGURATION_ERROR` for a missing
  URL and never assert raw DSN text.

- [ ] **Step 2: Run the factory tests and observe RED**

  Expected: import failure for `memory_store_factory`.

- [ ] **Step 3: Implement the factory**

  `legacy` and `disabled` return `None`. `postgres` and `neon` require the
  operator URL and construct a psycopg2 connection factory with
  `connect_timeout`. Unknown values raise `MemoryStoreConfigurationError`.
  Never catch a database error and instantiate `LocalVectorStore`.

- [ ] **Step 4: Add failing boundary-delegation tests**

  Assert the orchestrator and `_memory_dependencies()` each call the shared
  factory once and inject the returned SQL store into `MemoryBus`. Add a
  regression test proving that, in SQL mode, `_write_report_with_memory_bus`
  and `create_new_task_in_obsidian` do not perform a direct Obsidian write after
  canonical SQL failure.

- [ ] **Step 5: Wire both boundaries and remove SQL-mode split-brain fallback**

  Build the store at runtime and inject it. Keep direct fallback only for
  explicit legacy mode; PostgreSQL/Neon mode propagates the canonical failure
  or returns the MemoryBus `accepted` receipt.

- [ ] **Step 6: Run boundary tests GREEN**

  Run only the relevant node IDs first, then:

  ```bash
  .venv/bin/python -m pytest \
    src/tests/test_memory_store_factory.py \
    src/tests/test_api_bridge.py \
    src/tests/test_orchestrator_coverage.py -q
  ```

  Record pre-existing unrelated failures separately; do not weaken assertions.

---

### Task 5: Configuration, deployment contract, and operator documentation

**Files:**
- Modify: `.env.example`
- Modify: `src/.env.example`
- Modify: `conftest.py`
- Modify: `tests/conftest.py`
- Modify: `docs/MEMORY_BUS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `setup_secrets.sh` only if its existing template reconciliation does
  not already preserve newly declared operator values.

**Interfaces:**
- Consumes: the approved environment contract.
- Produces: operator-visible configuration with isolated test defaults.

- [ ] **Step 1: Add failing environment-isolation tests**

  Extend `src/tests/test_setup_secrets.py` to prove database URLs are preserved
  in sync mode, never generated during first setup, and never rotated by
  `--regenerate`. Add a subprocess test proving pytest clears live database
  URLs before importing application modules.

- [ ] **Step 2: Observe RED and update templates/guards**

  Add:

  ```dotenv
  ARTEMIS_MEMORY_BACKEND=legacy
  ARTEMIS_MEMORY_DATABASE_URL=
  ARTEMIS_MEMORY_MIGRATION_DATABASE_URL=
  ARTEMIS_MEMORY_DB_CONNECT_TIMEOUT_SECONDS=10
  ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS=5000
  ARTEMIS_MEMORY_OUTBOX_MAX_ATTEMPTS=10
  ARTEMIS_MEMORY_OUTBOX_RETRY_BASE_SECONDS=1
  ```

  Treat both URLs as operator-supplied values. Never include a real DSN or the
  supplied Obsidian bearer token.

- [ ] **Step 3: Correct authoritative docs**

  Update `MEMORY_BUS.md` and `ARCHITECTURE.md` from Obsidian-primary claims to
  SQL-primary/outbox semantics. Document `success` versus `accepted`, retry
  behavior, legacy rollout mode, direct-migration URL, pooled runtime URL, and
  rollback instructions.

- [ ] **Step 4: Validate the available Obsidian transport without persisting its secret**

  Use the operator's existing local MCP configuration or CLI to list tools and
  perform a write/read/delete round trip in an explicitly disposable test note.
  If the currently configured endpoint differs from the approved endpoint,
  report the mismatch and validate against a temporary local vault instead;
  do not rewrite desktop configuration implicitly.

- [ ] **Step 5: Run environment and documentation checks**

  Run:

  ```bash
  bash -n setup_secrets.sh
  .venv/bin/python -m pytest src/tests/test_setup_secrets.py -q
  git diff --check
  ```

---

### Task 6: Migration and release verification

**Files:**
- Inspect: all files changed by Tasks 1-5
- Update: this plan's checkboxes with verified outcomes

**Interfaces:**
- Consumes: local PostgreSQL 16 when available; otherwise a disposable
  PostgreSQL test service with no production credentials.
- Produces: evidence for every approved invariant.

- [ ] **Step 1: Apply the migration to disposable PostgreSQL**

  Use `ARTEMIS_MEMORY_MIGRATION_DATABASE_URL` only from an isolated test
  environment. Apply `db/migrations/0001_memory_write_through.sql` twice and
  verify the second application is safe or fails with a documented
  already-applied condition managed by the migration runner.

  Outcome: **unverified**. No disposable PostgreSQL, `psql`, or isolated
  migration DSN was available; Task 6 did not apply 0001 or claim a second-run
  result.

- [x] **Step 2: Run the focused memory suite**

  Run:

  ```bash
  .venv/bin/python -m pytest \
    src/tests/test_sql_memory_store.py \
    src/tests/test_obsidian_projection.py \
    src/tests/test_memory_bus.py \
    src/tests/test_memory_bus_integration.py \
    src/tests/test_memory_store_factory.py -q
  ```

  Outcome: executed with `-p no:cacheprovider`; the current focused suite plus
  Obsidian manager and projection coverage reported **105 passed**. This is
  v0001 compatibility evidence, not live PostgreSQL migration proof.

- [x] **Step 3: Run affected boundary and environment suites**

  Run relevant API bridge, orchestrator, Supabase compatibility, and secret
  setup tests. Compare failures with the pre-change baseline.

  Outcome: API bridge/coverage reported **164 passed**;
  orchestrator/dashboard/CLI reported **128 passed**; setup-secrets and
  Supabase compatibility reported **23 passed**. The parallel MemoryService
  suite reported **38 passed**, and its PostgreSQL-ledger unit surface reported
  **28 passed, 2 skipped** (live PostgreSQL unavailable and the unfinished 0002
  migration explicitly skipped). The separately maintained Compose structure
  suites reported **14 passed** after wiring both runtime surfaces. Across the
  recorded matrices this is **500 passed, 2 skipped, 0 failed**. Only a narrow
  43-test preflight baseline exists, so this broader result is fresh evidence
  rather than a before/after regression delta.

- [ ] **Step 4: Run static and secret checks on changed files**

  Run Black, Ruff, mypy on maintained Python boundaries, `git diff --check`,
  and the configured secret scanner. Search changed files for database URL
  schemes and bearer-token patterns; expected result is no credential value.

  Outcome: **partially clean, not a complete release gate**. `git diff
  --check`, maintained-module imports, `bash -n setup_secrets.sh`, TypeScript
  production `tsc --noEmit`, and Ruff F-class correctness checks passed. Broad
  Ruff formatting/line-length, Black, and mypy were not established as clean;
  the configured detect-secrets scanner and package-local Jest executable were
  unavailable. Filename-level pattern review identified fake test
  fixtures/source placeholder cases and no potential real credential.

- [x] **Step 5: Audit the end-state requirements**

  Confirm with source and test evidence that SQL owns canonical state, Obsidian
  failures return `accepted + sync_pending`, no SQL row is deleted as projection
  compensation, explicit Neon mode never falls back, both entry points share
  one factory, and no Hebbian/SEED behavior changed.

  Outcome: audited from current source and fresh focused/boundary tests. The
  parallel 0002-dependent surface is recorded as a dirty-checkout promotion
  risk, not as a v0001 Task 6 invariant failure.
