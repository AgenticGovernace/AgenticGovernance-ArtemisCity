# Implementation Notes for Artemis City

> **`CLAUDE.md` and `AGENTS.md` are byte-for-byte mirrors** so that every
> coding agent gets the same guidance — Claude reads `CLAUDE.md`, and
> non-Claude agents (Codex, Cursor, Aider, Replit, etc.) read `AGENTS.md`
> per the open AGENTS.md standard. Edit both in the same commit; CI fails
> if they drift.

This file is for AI agents and developers **editing code in this repo**. It
is intentionally narrow: it covers the active code surfaces, the
TypeScript ↔ Python bridge protocol, conventions for adding code, and
common traps. Architectural narrative, the LIVING_CITY metaphor, the
environment flow, and the test plan are owned by other documents — pointers
below.

If you are reading this to **understand what Artemis City is**, start with
`README.md` instead.

---

## Authoritative documents

`CLAUDE.md` defers to these. When they disagree with CLAUDE.md, **they
win**.

| Document | Owns |
|---|---|
| `README.md` | Project identity, three pillars, repo map, quick start |
| `docs/ARCHITECTURE.md` | System design — kernel, memory bus, governance, sandbox |
| `docs/MEMORY_BUS.md` | Write-through protocol, read hierarchy, conflict resolution |
| `docs/API_REFERENCE.md` | ATP message format and REST endpoint shapes |
| `docs/Agent Implementation Guide.md` | Dual-track Concept_Demos → src/ graduation path |
| `docs/LIVING_CITY.md` | The Mayor / Postmaster / City Manager metaphor |
| `docs/ENVIRONMENTS.md` | `dev → staging → prod` branch flow and `ARTEMIS_ENV` |
| `AGENTS.md` | Tool-neutral mirror of `CLAUDE.md` (for non-Claude agents) |
| `docs/TEST_PLAN.md` | Test plan (pyramid, coverage bars, naming convention) |
| `SECURITY.md` | Secret handling, key rotation, incident response |

---

## Active code surfaces

The repo ships several runtime layers. The table below tells you what is
authoritative, what is in transition, and what is deliberately frozen.

| Surface | Path | Role | Editing posture |
|---|---|---|---|
| Python core | `src/` | Orchestrator, agents, integration, governance, tests | **Authoritative**. Most work happens here. |
| Bridge | `src/api_bridge.py` | JSON stdin/stdout dispatch for the TS API | Extend by adding to `COMMANDS`. See "Bridge behavior" below. |
| FastAPI dashboard | `app/api/main.py` | `/api/*` dashboard backend, SQLite-only fallback | Edit for dashboard endpoints. Falls back to read-only SQLite if orchestrator imports fail. |
| TS Express API | `app/api/index.ts`, `app/api/v1/*.ts`, `app/api/controllers/*.ts` | `/api/v1/*` public HTTP boundary | Boundary for new registry / governance / ATP endpoints. Spawns the bridge — do **not** reimplement Python logic in TS. |
| Kernel layer | `app/kernel/` | In-process router with concrete `DaemonAgent`, `PlannerAgent` | Newer layer; growing toward orchestrator parity. Used by `app/kernel/cli.py` for local probing. |
| Obsidian MCP server | `src/Artemis Agentic Memory Layer/` | Standalone TypeScript MCP for the vault | Self-contained TS project; `npm run dev` / Docker. Independent of the Python core. |
| Frontend (mixed) | `app/web/frontend/` | React/Vite client; also carries leftover TS controllers/middleware | **In transition**. Treat as a mixed client/server workspace per README §"Dashboard and web-facing code". |
| Concept demos | `Concept_Demos/` | Prototype ground for agents and flows | Older but supported. Per the Agent Implementation Guide, work prototyped here graduates to `src/`. |

The Hatch wheel ships **only `src/` and `app/kernel/`** (see
`pyproject.toml` — `app/api`, `app/web`, `app/scripts` are explicitly
excluded so the wheel does not pull `fastapi`/`express` into consumers that
do not declare them).

---

## Bridge behavior (TS ↔ Python)

The TypeScript Express layer is the public HTTP boundary; the Python core
remains the single source of truth. They communicate by subprocess + JSON.
Do not call Python from TS any other way.

### Protocol

`app/api/lib/pythonBridge.ts` spawns:

```
python -m src.api_bridge
```

with `cwd = repo root`. It writes one JSON request to stdin and reads one
JSON envelope from stdout.

Request:

```json
{ "command": "<namespace>.<action>", "payload": { ... } }
```

Response:

```json
{ "ok": true,  "data":  { ... } }              // success
{ "ok": false, "error": "...", "code": "..." } // failure
```

### Error code → HTTP status (in `app/api/lib/pythonBridge.ts`)

| Bridge code | HTTP |
|---|---|
| `NOT_FOUND` | 404 |
| `INVALID_REQUEST`, `INVALID_JSON` | 400 |
| `UNKNOWN_COMMAND`, `BRIDGE_ERROR`, `INTERNAL_ERROR` | 500 |
| `BRIDGE_UNAVAILABLE` | 500 (set by the TS layer when the subprocess cannot be spawned) |

### Adding a new bridge command

1. Define a handler in `src/api_bridge.py` and register it in the
   `COMMANDS` dict (`namespace.action`).
2. Validate inputs via `_require(payload, "field")` and raise `BridgeError`
   with the right `code` for failure modes.
3. Add tests in `src/tests/test_api_bridge.py` covering both `dispatch()`
   in-process and the CLI stdin/stdout round-trip.
4. Wire it up on the TS side: add a thin controller method that calls
   `callBridge("namespace.action", payload)` and an Express route under
   `app/api/v1/`.

### Repo-root discovery for the bridge

`pythonBridge.ts` walks up from its own location looking for
`src/api_bridge.py`, so it works both under `ts-node-dev` and from the
compiled `dist/` layout. Override with `ARTEMIS_REPO_ROOT` if you need to
point it elsewhere. The Python interpreter is `python3` by default; override
with `ARTEMIS_PYTHON`.

---

## Governance data model

These live in `src/integration/` and `src/governance/`. They were
introduced in #74 (data model), #75 (HTTP boundary), and #76 (trust engine
+ approval tiers), so older notes may not mention them.

| Concern | File |
|---|---|
| Trust tiers, violations, quarantine | `src/integration/agent_registry.py` (extends the `agents` table via idempotent `ALTER TABLE` migration; `violations` table; `record_violation`, `clear_violations`, `set_trust_tier`) |
| Sandbox enforcement | `src/integration/sandbox.py` (`AgentSandbox`, `ToolPolicy`; 3-strike quarantine via the registry) |
| Checkpoints + rollback | `src/governance/checkpoints.py` (JSON files with SHA-256 integrity hash, retention window, `RollbackManager`) |
| Trust-score formula | `src/governance/trust.py` (weighted sub-metrics — see the module docstring for the spec-typo note about the security sign) |
| Approval tiers | `src/governance/approvals.py` (`SelfUpdateGovernor` → `auto | monitored | human`) |

For the *why* and the spec these implement, read `docs/ARCHITECTURE.md`
and `docs/API_REFERENCE.md`.

---

## Conventions

### Adding a Python agent

1. Prototype in `Concept_Demos/` if the design is uncertain (per
   `docs/Agent Implementation Guide.md`).
2. Implement `BaseAgent` from `src/agents/base_agent.py`; provide
   `name`, `capabilities`, and `perform_task(task_context: dict) -> dict`.
3. Register the agent in the orchestrator's `__init__`
   (`src/mcp/orchestrator.py`).
4. Add unit tests under `src/tests/` per `docs/TEST_PLAN.md` (naming:
   `test_<module>_<function>_<scenario>`).

### Adding an HTTP endpoint

For anything in the registry / governance surface: extend the **bridge**
(see above), then add a TS controller + route. Never reimplement Python
logic in TypeScript — the bridge is the contract.

For dashboard-flavoured endpoints fronting the SQLite databases: add to
`app/api/main.py` (FastAPI), respecting the `X-API-Key` auth pattern
already used there.

### Tests

`docs/TEST_PLAN.md` is the canonical test plan (pyramid, coverage targets,
naming, marker conventions). Don't restate it here. To run the suite
locally: `make test` (calls `pytest src/tests/`). CI runs the same on
Python 3.10 / 3.11 / 3.12 plus a config-validation step.

### Environment variables and secrets

`./setup_secrets.sh` is the canonical provisioner. It writes four files,
each picked up by its own consumer:

| File | Read by |
|---|---|
| `.env` | Python core, FastAPI dashboard |
| `app/api/.env` | TS Express API (loaded via `dotenv/config` at the top of `app/api/index.ts`) |
| `src/.env` | Memory-layer Python |
| `src/Artemis Agentic Memory Layer/.env` | Standalone MCP server (if present) |

Keys generated: `MCP_API_KEY` (shared across all files), `FASTAPI_API_KEY`
(dashboard only), `ARTEMIS_API_KEY_DEFAULT` (TS Express auth, written as a
`key:role:perms` tuple). Re-running prompts before overwriting each file.

---

## Common traps

- **Do not use the old branding.** Earlier notes called this "XMCP" /
  "MCP" — that naming is dead. The project is **Artemis City**.
- **Do not use the old `web/` paths.** Code lives under `app/api/` and
  `app/web/frontend/`. Anything referencing `web/api/main.py` or
  `web/frontend/` is stale.
- **Do not add `fastapi` / `express` to runtime dependencies in the
  wheel.** `pyproject.toml` excludes `app/api`, `app/web`, `app/scripts`
  from the wheel for exactly this reason.
- **Do not call Python from TypeScript outside the bridge.** Every
  registry / governance call goes through `pythonBridge.ts`. Adding a
  parallel path forks the source of truth.
- **Do not duplicate the LIVING_CITY metaphor here.** Mention agents by
  their function (orchestrator, memory layer, etc.) and let
  `docs/LIVING_CITY.md` own the metaphor. The metaphor is a deliberate
  framing choice — don't water it down by paraphrasing it elsewhere.
- **Do not assume `dev` exists.** Past promotions auto-deleted it; if
  you need to branch, branch off `prod` (see `docs/ENVIRONMENTS.md`).

---

## How to run things (cheat-sheet)

See `README.md` for the long form. The Makefile is the canonical entry
point.

| Action | Command |
|---|---|
| Generate `.env` files | `./setup_secrets.sh` |
| Install runtime deps | `make install` |
| Install dev tooling | `make install-dev` |
| Run tests | `make test` |
| Run tests with coverage | `make test-cov` |
| Lint | `make lint` (read-only) / `make lint-fix` (mutating) |
| All quality checks | `make check` |
| Security scans | `make security` |
| Python CLI | `make run` (runs `src/launch/main.py`) |
| Concept demos | `make demo` |
| Obsidian MCP server | `make server` |
| Frontend dev server | `make frontend` |
| Build wheel | `make build` |

---

## Quick reference — which file owns what

| Concern | File |
|---|---|
| Orchestrator entry | `src/mcp/orchestrator.py` |
| Agent base class | `src/agents/base_agent.py` |
| Agent registry + scoring + governance | `src/integration/agent_registry.py` |
| Memory bus (write-through, read hierarchy) | `src/integration/memory_bus.py` |
| Trust interface (level/decay/permissions) | `src/integration/trust_interface.py` |
| Sandbox enforcement | `src/integration/sandbox.py` |
| Vector store (semantic search) | `src/mcp/vector_store.py` |
| Hebbian weights | `src/mcp/hebbian_weights.py` |
| Governance monitor (failure streaks) | `src/integration/governance.py` |
| Checkpoints / rollback | `src/governance/checkpoints.py` |
| Trust-score engine | `src/governance/trust.py` |
| Approval tiers | `src/governance/approvals.py` |
| TS ↔ Python bridge (Python side) | `src/api_bridge.py` |
| TS ↔ Python bridge (TS side) | `app/api/lib/pythonBridge.ts` |
| TS API routes | `app/api/v1/*.ts` |
| FastAPI dashboard | `app/api/main.py` |
| Kernel layer | `app/kernel/kernel.py`, `app/kernel/agents/*.py` |
| ATP parser / validator | `src/agents/atp/` |
| Environment loader | `src/utils/environments.py` |
| Test conftest | `src/tests/conftest.py` |
