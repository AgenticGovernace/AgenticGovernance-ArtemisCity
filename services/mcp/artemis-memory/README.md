# artemis-memory-mcp

Governed Model Context Protocol server exposing the canonical Artemis City
memory ledger (`src/memory/service.py`) as four MCP tools: `write-memory`,
`read-memory`, `search-memory`, and `get-memory-status`.

`src/` remains the sole domain-logic owner. This package is a thin transport
adapter: it resolves a transport principal, authorizes the request through
`GovernedGate` (strict ATP validation, capability, and namespace scope), and
converts the result to a typed MCP response. See
`docs/superpowers/specs/2026-08-16-artemis-mcp-backend-servers-design.md` for
the accepted design this package implements.

## Configuration

PostgreSQL/Neon is the canonical ledger; Obsidian and the vector index are
best-effort projections. Nothing is opened at import time — configuration is
validated and connections are built lazily per operation.

| Variable | Required by | Purpose |
|---|---|---|
| `ARTEMIS_MEMORY_DATABASE_URL` | stdio and HTTP | PostgreSQL/Neon connection string for the canonical ledger. **Operator-supplied secret.** |
| `ARTEMIS_MEMORY_DB_CONNECT_TIMEOUT_SECONDS` | optional | Connection timeout in seconds (default `10`). |
| `ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS` | optional | Per-statement timeout in milliseconds (default `5000`). |
| `OBSIDIAN_VAULT_PATH` | stdio and HTTP | Vault root for the Obsidian projection (see `src/mcp/config.py`). |
| `ARTEMIS_VECTOR_BACKEND` | optional | `sqlite` (default, always available) or `supabase`. An explicit `supabase` selection that cannot be constructed fails setup rather than silently falling back to SQLite. |
| `ARTEMIS_SUPABASE_DB_URL` | when `ARTEMIS_VECTOR_BACKEND=supabase` | Postgres connection string for the vector backend. **Operator-supplied secret.** |
| `ARTEMIS_MCP_PRINCIPAL_ID` | stdio only | The local service principal's identity. |
| `ARTEMIS_MCP_CAPABILITIES` | stdio only | Comma-separated capability/scope grants, e.g. `memory:write,memory:read,memory:namespace:*`. |
| `ARTEMIS_MCP_BEARER_TOKEN` | `--http` only | The single accepted bearer token. **Operator-supplied secret.** |
| `ARTEMIS_MCP_HTTP_CLIENT_ID` | `--http` only | Client ID reported for a verified bearer token. |
| `ARTEMIS_MCP_HTTP_SUBJECT` | `--http` only | Principal subject reported for a verified bearer token. |
| `ARTEMIS_MCP_HTTP_SCOPES` | `--http` only | Comma-separated capability/scope grants for the bearer token, same vocabulary as `ARTEMIS_MCP_CAPABILITIES`. Must include the transport-wide `artemis:memory` scope. |
| `ARTEMIS_MCP_AUTH_ISSUER_URL` | `--http` only | OAuth issuer URL advertised to clients. |
| `ARTEMIS_MCP_RESOURCE_SERVER_URL` | `--http` only | This server's own resource URL, e.g. `https://memory.example.com`. |

Namespace grants use `memory:namespace:{namespace}` for one namespace, or the
server-recognized `memory:namespace:*` wildcard for all namespaces. A grant
of `memory:write` or `memory:read` alone is not sufficient — every tool call
also requires the matching namespace scope.

## Running

Default transport is stdio:

```bash
export ARTEMIS_MEMORY_DATABASE_URL=postgresql://...
export ARTEMIS_MCP_PRINCIPAL_ID=local-operator
export ARTEMIS_MCP_CAPABILITIES=memory:write,memory:read,memory:namespace:*
uv run artemis-memory-mcp
```

Authenticated Streamable HTTP at `/mcp`:

```bash
export ARTEMIS_MEMORY_DATABASE_URL=postgresql://...
export ARTEMIS_MCP_BEARER_TOKEN=...
export ARTEMIS_MCP_HTTP_CLIENT_ID=artemis-mcp
export ARTEMIS_MCP_HTTP_SUBJECT=memory-service
export ARTEMIS_MCP_HTTP_SCOPES=artemis:memory,memory:write,memory:read,memory:namespace:*
export ARTEMIS_MCP_AUTH_ISSUER_URL=https://issuer.example.com
export ARTEMIS_MCP_RESOURCE_SERVER_URL=https://memory.example.com
uv run artemis-memory-mcp --http --host 0.0.0.0 --port 8000
```

## Migration

This package targets the `0002_memory_server_contract.sql` schema evolution
of `db/migrations/0001_memory_write_through.sql` (namespace/key identity,
principal and provenance columns, the `vector` outbox target, and the
`memory_completion_provenance` table). **That migration has not shipped
yet** — apply `0001` and `0002` to the target database, in order, against a
verified disposable environment before pointing `ARTEMIS_MEMORY_DATABASE_URL`
at a production database.

## Projection failures

A projection (Obsidian or vector) failure never removes the committed SQL
record. `get-memory-status` reports each requested projection as `pending`,
`succeeded`, `failed`, or `skipped`; a `failed` projection remains retryable
through the durable outbox and is never silently reported as delivered.
