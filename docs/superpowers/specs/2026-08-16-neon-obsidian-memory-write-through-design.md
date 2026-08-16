# Neon and Obsidian Memory Write-Through Design

**Date:** 2026-08-16

**Status:** Approved

## Goal

Make Neon-compatible PostgreSQL the durable source of truth for Artemis City
memory while preserving Obsidian as the human-readable projection. A successful
SQL commit remains accepted when Obsidian is temporarily unavailable and is
reported as `sync_pending` until projection succeeds.

## Scope

This change covers the canonical memory write path, its PostgreSQL schema,
Obsidian delivery, configuration, retries, and focused contract tests. It does
not change Hebbian calculations, trust learning, SEED handling, or embedding
policy. The vector index remains a derived semantic index.

The supplied local Obsidian MCP/CLI endpoint may be used as an operational
adapter, but its bearer credential is operator-owned configuration. It is never
committed, logged, copied into a client bundle, or required by unit tests. The
existing vault-backed `ObsidianManager` remains the first projection adapter.

## Authority and state

PostgreSQL owns durable memory identity, content, revision ordering,
idempotency, and projection state. Obsidian owns no canonical state; it renders
the latest committed revision for people and compatible tools.

One short PostgreSQL transaction writes:

1. an immutable memory revision;
2. the current head for the exact vault-relative path; and
3. one uniquely keyed Obsidian outbox event.

Only after commit may projection delivery begin. There is no attempted
cross-system rollback because PostgreSQL and a filesystem or MCP server cannot
participate in one ACID transaction.

## Data model

The provider-neutral schema lives under `db/migrations/`, not under the legacy
Supabase migration tree.

### `artemis.memory_records`

- `record_id UUID PRIMARY KEY`
- `memory_id UUID NOT NULL`
- `relative_path TEXT NOT NULL`
- `revision BIGINT NOT NULL`
- `idempotency_key TEXT NOT NULL UNIQUE`
- `content TEXT NOT NULL`
- `content_sha256 CHAR(64) NOT NULL`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `provenance_id UUID NULL`
- `source_agent TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- unique `(memory_id, revision)`

### `artemis.memory_heads`

- `relative_path TEXT PRIMARY KEY`
- `memory_id UUID NOT NULL UNIQUE`
- `current_record_id UUID NOT NULL`
- `current_revision BIGINT NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

The head update locks one path while assigning the next revision. The exact
validated path is retained; path-to-ID normalization is not used. Paths are
NFC-normalized, use exact `/` separators, name a supported file leaf, and may
not place a file-like segment above another note. SQL also rejects
case-insensitive aliases so default macOS vault semantics cannot create two
heads for one filesystem target.

### `artemis.memory_outbox`

- `event_id UUID PRIMARY KEY`
- `record_id UUID NOT NULL`
- `memory_id UUID NOT NULL`
- `relative_path TEXT NOT NULL`
- `revision BIGINT NOT NULL`
- `target TEXT NOT NULL CHECK (target = 'obsidian')`
- `operation TEXT NOT NULL CHECK (operation IN ('write', 'delete'))`
- `status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'delivered', 'dead'))`
- `attempt_count INTEGER NOT NULL DEFAULT 0`
- `next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `locked_at TIMESTAMPTZ NULL`
- `locked_by TEXT NULL`
- `last_error_code TEXT NULL`
- `delivered_at TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- unique `(record_id, target)`

Pending work is indexed by `status, next_attempt_at, revision`. A projector
must compare the event revision with the current head before writing so an old
retry cannot overwrite a newer note.

## Python contracts

`src/integration/sql_memory_store.py` owns transport-independent models and the
PostgreSQL adapter:

```python
@dataclass(frozen=True)
class MemoryRevision:
    record_id: str
    memory_id: str
    relative_path: str
    revision: int
    idempotency_key: str
    content: str
    content_sha256: str
    metadata: dict[str, object]
    provenance_id: str | None
    source_agent: str | None
    created_at: datetime


@dataclass(frozen=True)
class MemoryWriteReceipt:
    revision: MemoryRevision
    event_id: str
    projection_status: str
    duplicate: bool


class SqlMemoryStore(Protocol):
    def stage_write(...) -> MemoryWriteReceipt: ...
    def mark_delivered(event_id: str) -> None: ...
    def mark_projection_failed(event_id: str, error_code: str) -> None: ...
    def get_current(relative_path: str) -> MemoryRevision | None: ...
    def list_current(prefix: str = "", limit: int | None = None) -> list[MemoryRevision]: ...
    def projection_guard(relative_path: str) -> ContextManager[MemoryRevision | None]: ...
    def list_pending(limit: int = 100) -> list[MemoryWriteReceipt]: ...
```

`PostgresMemoryStore` uses a connection factory, short context-managed
transactions, parameterized SQL, and no runtime DDL. Explicit PostgreSQL/Neon
selection fails closed; it never silently substitutes SQLite.

## Write state machine

`MemoryBus.write_note_with_embedding()` keeps its compatibility surface and
adds optional `idempotency_key`, `provenance_id`, and `source_agent` inputs.

1. Validate the vault-relative path and content.
2. Derive or accept a stable idempotency key and compute SHA-256.
3. Commit the immutable revision, head, and outbox event in PostgreSQL.
4. Update the semantic vector projection when `embed=True`.
5. Attempt deterministic full-file Obsidian projection.
6. Mark the event delivered only after projection confirms.

The client-visible receipt adds `memory_id`, `record_id`, `revision`,
`content_sha256`, `idempotency_key`, `sql_status`, `obsidian_status`,
`sync_pending`, and `duplicate` while retaining existing response keys.

### Outcome rules

| Condition | Result |
|---|---|
| Validation fails | Raise; no SQL, vector, or Obsidian side effect. |
| PostgreSQL transaction fails | Raise retryable storage error; no Obsidian write. |
| PostgreSQL commits and Obsidian succeeds | `status=success`, `sync_pending=false`. |
| PostgreSQL commits and Obsidian fails | `status=accepted`, `sync_pending=true`; retain pending event. |
| Delivery acknowledgement fails after file replacement | `status=accepted`, `sync_pending=true`; replay the same deterministic overwrite. |
| Duplicate idempotency key with identical request | Return original revision; do not create another record or event. |
| Duplicate idempotency key with different content/path | Raise idempotency conflict. |
| Older event is overtaken by a newer head | Mark it delivered/superseded without overwriting the newer note. |

The transaction that installs a newer head also supersedes older actionable
outbox events for that exact path. This keeps pending work aligned with the
only revision that may be projected.

In PostgreSQL mode, direct Obsidian fallback is forbidden. A caller may not
turn a failed canonical write into an Obsidian-only success.

## Obsidian projection

Projection always uses deterministic full-file overwrite. The projected body
is the committed SQL content; retries do not generate a new timestamp or append
text. `ObsidianManager` writes through a unique temporary file in the target
directory, flushes and `fsync`s it, calls `os.replace`, then `fsync`s the parent
directory. A failed replacement leaves the existing note intact.

The first adapter writes a configured local vault. The projector boundary is
kept narrow so the available local MCP or CLI transport can implement the same
`write_note(relative_path, content, overwrite=True)` behavior without changing
the memory state machine.

## Configuration

```dotenv
ARTEMIS_MEMORY_BACKEND=legacy
ARTEMIS_MEMORY_DATABASE_URL=
ARTEMIS_MEMORY_MIGRATION_DATABASE_URL=
ARTEMIS_MEMORY_DB_CONNECT_TIMEOUT_SECONDS=10
ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS=5000
ARTEMIS_MEMORY_OUTBOX_MAX_ATTEMPTS=10
ARTEMIS_MEMORY_OUTBOX_RETRY_BASE_SECONDS=1
OBSIDIAN_VAULT_PATH=
```

The two database URLs and Obsidian credentials/paths are operator supplied.
`setup_secrets.sh` preserves them and never generates or rotates them. Runtime
uses Neon's pooled endpoint; migrations use its direct endpoint. Ordinary tests
clear these variables before imports and use injected fakes or disposable local
PostgreSQL only.

`legacy` preserves the existing local bus until an operator explicitly enables
`postgres` or `neon`. Explicit SQL mode is fail-closed. This is a rollout
compatibility switch, not silent fallback.

## Verification

The implementation is not complete until tests prove:

- SQL transaction failure never touches Obsidian;
- record, head, and event roll back together;
- idempotent replay creates one revision and event;
- Obsidian failure retains a readable SQL revision and pending event;
- retry writes deterministic bytes and marks delivery once;
- stale revisions cannot overwrite newer projections;
- canonical list/read paths do not depend on Obsidian projection freshness;
- the projection guard holds the same exact-path fence as a writer;
- explicit Neon selection never becomes SQLite;
- `embed=False` still writes canonical SQL;
- orchestrator and bridge share the same configured memory-store factory; and
- no supplied bearer token appears in source, logs, fixtures, or generated
  client assets.
