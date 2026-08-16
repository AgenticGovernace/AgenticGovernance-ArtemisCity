# Memory Bus Specification

## Authority and rollout

The Memory Bus is the single write coordinator for durable agent memory. In
`legacy` mode it retains the existing vault-backed behavior for a reversible
rollout. In explicit `postgres` or `neon` mode, PostgreSQL is authoritative:
it owns memory identity, content, revisions, idempotency, and projection state.
Obsidian is a human-readable projection, and the vector store remains a derived
semantic index. Neither may become an Obsidian-only substitute for a failed SQL
write.

`ARTEMIS_MEMORY_BACKEND=legacy` is the default. An operator must deliberately
select `postgres` or `neon`. An unsupported backend or missing/invalid runtime
database setting fails closed as `MEMORY_DATABASE_CONFIGURATION_ERROR`. The
store connects lazily; a connection or query failure after valid configuration
is reported separately as `MEMORY_STORAGE_UNAVAILABLE`.

## SQL ledger and outbox

One short PostgreSQL transaction creates an immutable memory revision, updates
the current head for its vault-relative path, and inserts one uniquely keyed
Obsidian outbox event. The database schema is in
`db/migrations/0001_memory_write_through.sql`.

```text
Caller
  -> validate vault-relative path and content
  -> commit record + head + outbox event in one SQL transaction
  -> construct each local projection only when it is first needed
  -> update vector projection when embed=True
  -> immediately attempt deterministic full-file Obsidian projection
  -> mark outbox delivered only after projection acknowledgement
```

The projector holds the same PostgreSQL transaction-scoped advisory path locks
as canonical writers while it compares the event with the current head and
updates both derived projections. This closes the stale-event check/write race
across processes. The initial slice performs one immediate projection attempt;
it does not run a background projector or automatic retry loop.

## Client-visible outcomes

| Condition | Result |
|---|---|
| SQL commit and Obsidian projection succeed | `status=success`, `sync_pending=false` |
| SQL commit succeeds but vector projection fails | `status=accepted`, `vector_status=pending`, `sync_pending=true`; Obsidian is not attempted |
| SQL commit succeeds but projection or acknowledgement fails | `status=accepted`, `sync_pending=true` |
| SQL transaction fails | raise a storage error; do not write Obsidian |
| Idempotent replay of the same request | return the original revision and receipt with `duplicate=true` |
| Same idempotency key with different path or content | raise an idempotency conflict |
| Replay of an older explicit key after a newer revision | `status=superseded`, `obsidian_status=superseded`, `sync_pending=false`; do not overwrite current projections |

An `accepted` result is durable: callers can read the committed SQL revision
immediately even though its Obsidian mirror is pending. It is not a failed
write, and it must not be converted to a direct Obsidian fallback.

Receipts retain compatibility fields and include `memory_id`, `record_id`,
`revision`, `content_sha256`, `idempotency_key`, `sql_status`,
`obsidian_status`, `vector_status`, `sync_pending`, and `duplicate`.
`vector_status` is `delivered` after a successful embedding, `skipped` when
`embed=False`, and `pending` after a post-commit vector failure.

Each SQL-mode invocation without an `idempotency_key` receives a new opaque UUID
operation key, returned in the receipt. Repeating the same content without
supplying a prior key is a new write: `A -> B -> A` creates revisions 1, 2, and
3. Idempotent retry is guaranteed only when the caller supplies and reuses the
same nonempty string key (including by taking the generated key from an earlier
receipt and explicitly sending it on replay).

The mounted Express endpoint is `POST /api/v1/memory/write`. Its JSON body is:

```json
{
  "path": "Notes/example.md",
  "content": "# Canonical memory",
  "metadata": {},
  "embed": true,
  "idempotency_key": "optional-operation-key",
  "provenance_id": "optional-uuid",
  "source_agent": "optional-agent-name"
}
```

It returns HTTP 200 when the requested projections are synchronized and HTTP
202 when SQL accepted the revision but `sync_pending=true`. Both responses put
the canonical receipt in `data`. The idempotency key returned there must be
retained if the caller may need to replay a pending projection.

Write paths are NFC-normalized POSIX-style vault-relative file paths. They must
use `/`, name a suffixed file leaf such as `.md`, and contain no `.`/`..`, empty
segments, backslashes, case-insensitive aliases, or parent directory segment
that looks like a file (for example `v1.0/note.md`). Invalid paths are rejected
before SQL.

## Reads and projections

In SQL mode, exact-path reads query the SQL current head before consulting
Obsidian, so read-after-write works during a projection outage. The public
exact-read boundary never converts keyword or vector results into an exact
match, and a missing SQL head does not expose orphaned vault bytes. SQL-mode
query search uses an optional exact SQL path followed by the derived vector
index; it does not scan the Obsidian projection for keywords. Consequently, a
record written with `embed=False` or with a pending vector projection remains
exact-path readable but is not query-discoverable until its vector projection
exists. Vault keyword fallback remains available only in `legacy` mode.
`embed=False` disables only the vector projection; canonical SQL still commits.
The bridge does not construct the local vector or Obsidian adapter for an exact
SQL read. On writes it commits SQL before the first adapter construction
attempt, so an unavailable adapter becomes a pending projection rather than a
gate on canonical durability.

`memory.list` and `memory.stats` also query canonical SQL heads in SQL mode.
Their responses are labeled `source=sql`. SQL stats return
`vector_count=null` and `projection_stats=not_checked`; they do not fabricate a
derived-index count or hide a canonical database outage.

Canonical delete/tombstone semantics are not part of this slice. The bridge
rejects `memory.delete` in SQL mode with `MEMORY_DELETE_UNSUPPORTED` before it
constructs or mutates local projections. Legacy delete behavior is unchanged.

Obsidian projection uses deterministic full-file overwrite. The local adapter
writes a unique same-directory temporary file, flushes and fsyncs it, replaces
the target atomically, then fsyncs the parent directory. A replacement failure
leaves the old note intact.

## Projection replay in this slice

When the immediate projection attempt fails, the committed SQL revision and
pending outbox row remain durable and the caller receives `accepted` with
`sync_pending=true`. There is no background projection worker, automatic or
bounded exponential backoff, max-attempt/dead transition, or operator command
that resumes a worker in this first slice. A pending row can remain pending
indefinitely when nobody replays it.

Retry is caller-driven: after restoring projection connectivity, replay the
same write with the same idempotency key. That idempotent replay reuses the
original committed revision and attempts its deterministic projection again; it
does not append, create a new revision, or substitute an Obsidian-only write.
Delivered duplicates also rerun the requested deterministic projections. This
is necessary when an earlier replay used `embed=False`: a later replay with
`embed=True` performs a real idempotent vector upsert before reporting
`vector_status=delivered`.

When a newer revision becomes the head for the same path, its SQL transaction
marks older pending/processing Obsidian events delivered with
`superseded_by_newer_revision`. Obsolete revisions therefore do not accumulate
as actionable outbox work and cannot overwrite the current projection.

Internal orchestrator writes retain the returned operation key and event ID in
their structured receipt/log state. Task creation and status updates accept an
optional replay key, and `get_memory_projection_receipt(path)` returns the
latest retained handle so the current committed revision can be resubmitted.
This is caller/operator replay, not an automatic outbox worker.

## Initial rollout constraints

- Run exactly one task-executing orchestrator worker. Pending-task discovery is
  SQL-authoritative, but this slice does not yet provide an atomic SQL
  compare-and-set claim or lease for competing workers.
- Existing installations must rebuild or reset the derived vector index once.
  Older releases replaced spaces with underscores in vector IDs; retaining
  those rows beside canonical-path IDs can produce stale duplicate search hits.
  This does not delete or rewrite canonical SQL revisions.
- Build the Express API (`npm run build` in `app/api`) before `npm start`.
  `app/api/dist` is ignored and must be generated from the checked-in
  TypeScript source for each deployment.
- Apply the migration only to an isolated/disposable database first. Live Neon
  syntax, first application, and repeat-application behavior remain rollout
  gates until exercised against PostgreSQL.

The Express bridge maps canonical-memory failures as follows:

| Bridge code | HTTP status |
|---|---:|
| `MEMORY_IDEMPOTENCY_CONFLICT` | 409 |
| `MEMORY_STORAGE_UNAVAILABLE` | 503 |
| `MEMORY_DATABASE_CONFIGURATION_ERROR` | 503 |
| `MEMORY_DELETE_UNSUPPORTED` | 409 |

`ARTEMIS_MEMORY_OUTBOX_MAX_ATTEMPTS` and
`ARTEMIS_MEMORY_OUTBOX_RETRY_BASE_SECONDS` are reserved/inert configuration
fields in this slice. They are not implemented runtime controls and must not
be interpreted as a retry schedule or dead-letter policy.

## Configuration and ownership

```dotenv
ARTEMIS_MEMORY_BACKEND=legacy
ARTEMIS_MEMORY_DATABASE_URL=
ARTEMIS_MEMORY_MIGRATION_DATABASE_URL=
ARTEMIS_MEMORY_DB_CONNECT_TIMEOUT_SECONDS=10
ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS=5000
ARTEMIS_MEMORY_OUTBOX_MAX_ATTEMPTS=10
ARTEMIS_MEMORY_OUTBOX_RETRY_BASE_SECONDS=1
OBSIDIAN_VAULT_PATH=
OBSIDIAN_API_KEY=
```

Both database URLs, the Obsidian vault path, and Obsidian credentials are
operator-supplied. `setup_secrets.sh` preserves configured values during sync
and `--regenerate`; it never generates, rotates, logs, or copies them into
client assets. Leave all of them blank in committed templates.

For Neon, `ARTEMIS_MEMORY_DATABASE_URL` is the pooled runtime endpoint and
`ARTEMIS_MEMORY_MIGRATION_DATABASE_URL` is the direct endpoint for a manually
invoked `psql` migration command. The application never runs DDL, and no
repository migration runner currently consumes that variable. Do not point
application runtime traffic at the direct URL. The migration is internally
atomic: it holds a transaction-scoped advisory migration lock, records version
`0001_memory_write_through` before its domain DDL, and commits both the version
row and schema changes together. A repeat fails before domain DDL with
`P0001` and `migration 0001_memory_write_through is already applied`. Run the
internally transactional migration with fail-fast `psql` handling:

```bash
psql "$ARTEMIS_MEMORY_MIGRATION_DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/0001_memory_write_through.sql
```

Live first application and repeat-application behavior have not been verified
against PostgreSQL and remain deployment gates; the application never runs this
DDL.

Both connection and statement timeout settings must be positive integers. The
runtime passes the statement deadline to PostgreSQL as a connection option;
neither setting is interpolated into SQL or exposed in error responses.

Tests clear live database URLs and Obsidian credentials before application
imports and use injected fakes or a disposable local vault.

## Rollback

To roll back an application deployment, set `ARTEMIS_MEMORY_BACKEND=legacy`
and redeploy the prior compatible release. This stops new SQL-ledger writes but
does not delete existing SQL revisions or outbox events. Preserve the ledger
and take a database backup before any data-retention decision. Return to SQL
mode only after verifying the configured pooled URL, migration state, and
any pending outbox rows. Those rows require caller-driven idempotent replay in
this slice; they are not drained by a background worker.
