# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Three implementation surfaces (read this first)

The repo contains three overlapping Python/TS code trees. Knowing which is "live" for a given task prevents wasted edits:

1. **`src/`** — Authoritative Python core. `src/mcp/orchestrator.py` wires `AgentRegistry` (`src/integration/agent_registry.py`), `MemoryBus`, `GovernanceMonitor`, `HebbianWeightManager`, and `LocalVectorStore`. `src/api_bridge.py` is the JSON command bridge invoked over stdin/stdout by the TS API. Tests live under `src/tests/`.
2. **`app/`** — Newer kernel + TS HTTP boundary. `app/kernel/` is a "de-codex'd" Python kernel (`kernel.py`, `agent_router.py`, `memory_bus.py`, agents under `app/kernel/agents/`). `app/api/` is the Express/TypeScript HTTP layer that shells out to `src/api_bridge.py` via `app/api/lib/pythonBridge.ts`. `app/web/frontend/` is the React/Vite dashboard. `app/api/main.py` is a separate FastAPI dashboard backend that imports from `src/`.
3. **`Concept_Demos/src/`** — Older prototype tree (parser, generator, hebbian_weights, vector_store, integration/*). Test conftest still appends it to `sys.path` for legacy modules like `exceptions`.

When a task crosses trees, `src/` is the source of truth for agent/governance state; `app/api` is the public HTTP boundary; `Concept_Demos` is reference material — don't move modules between them without updating `src/tests/conftest.py` and the import-duality blocks (`try: absolute except ImportError: relative`) that exist across modules.

## Architecture invariants worth preserving

- **TS-to-Python bridge is stdin/stdout JSON.** `app/api/lib/pythonBridge.ts` spawns `python -m src.api_bridge` per call. The contract: `{"command": "<namespace>.<action>", "payload": {...}}` in, `{"ok": true, "data": ...}` or `{"ok": false, "error": ..., "code": ...}` out. Error codes map to HTTP status via `CODE_TO_STATUS`. Keep the bridge stdlib-only — no web framework on the Python side — so it stays CI-testable.
- **Agent routing.** `AgentRegistry.route_task()` selects the highest composite score (`alignment*0.4 + accuracy*0.4 + efficiency*0.2`) among agents whose capabilities match `required_capability`.
- **Memory write path.** `MemoryBus.write_note_with_embedding()` writes vector store first, then the Obsidian note; on file-write failure it rolls back the vector insert. Read path is exact note lookup → keyword scan → vector fallback.
- **Trust + governance.** Trust tiers (`auto`/`monitored`/`human`) and violation tracking are constants in `src/integration/agent_registry.py`; `QUARANTINE_THRESHOLD = 3` triggers quarantine. `integration/trust_interface.py` gates ops by trust level; `integration/postal_service.py` checks trust before archive/mail writes.
- **ATP protocol.** Minimum complete header set is Mode / Context / ActionType. `ATPValidator` defaults to `strict=False` (missing headers → warnings, not failures). Accepted header styles include both `#Mode: Build` and `[[Mode]]: Review` (see `src/tests/conftest.py` fixtures).
- **Status dict contract.** Tests assert exact shapes — keep `{"status": "success|failed", ...}` stable across orchestrator/agent return values.

## Commands

### Python
```bash
# Install (use whichever resolver is set up locally)
pip install -r requirements.txt
pip install -r requirements-dev.txt    # for tests/lint

# Tests — pyproject.toml sets testpaths=src/tests with strict markers
python -m pytest src/tests
python -m pytest src/tests/test_agent_routing.py -v
python -m pytest src/tests -k "memory_bus" -v
python -m pytest src/tests -m "unit"     # markers: unit, integration, e2e, slow, requires_server

# Lint / format (Makefile shortcuts)
make check    # black --check, isort --check-only, flake8, mypy
make lint-fix # black + isort write
make security # bandit + safety
```

### TypeScript API (`app/api`)
```bash
cd app/api
npm install
npm run dev    # ts-node-dev hot reload on PORT=4000
npm run build && npm start
```

### Frontend (`app/web/frontend`)
```bash
cd app/web/frontend
npm install
npm run dev    # Vite dev server
npm run build  # tsc -b && vite build
```

### Memory Layer MCP server (`src/Artemis Agentic Memory Layer/`)
```bash
cd "src/Artemis Agentic Memory Layer"
npm install
npm run dev    # nodemon ts-node src/index.ts
```

### Demos
```bash
python Concept_Demos/demo_artemis.py
python Concept_Demos/demo_city_postal.py            # works offline via mocks
python Concept_Demos/demo_memory_integration.py     # skips MCP flows if server down
cd Concept_Demos && python3 -m http.server 8080     # browser prototypes
```

## Environment + config

- Active environment selected by `ARTEMIS_ENV` (`dev`/`staging`/`prod`), loaded by `src/utils/environments.py` from `config/environments/<env>.yaml`. CI validates all three configs.
- Branching: feature → `dev` → `staging` → `prod`. `prod` is the default/protected branch — feature PRs target `dev`. Promotion via the `Promote` workflow or manual PR (see `docs/ENVIRONMENTS.md`).
- Key env vars (see `.env.example`): `MCP_BASE_URL`, `MCP_API_KEY`, `OBSIDIAN_BASE_URL`, `OBSIDIAN_API_KEY`, `OBSIDIAN_VAULT_PATH`, `AGENT_INPUT_DIR`/`AGENT_OUTPUT_DIR` (vault-relative), `ARTEMIS_REGISTRY_DB` (sqlite path used by the bridge).
- Vector store default: SQLite at `data/vector_store.db` with deterministic local embeddings (offline-safe for tests).

## Safe change patterns

- Don't break the import duality (`try: absolute except ImportError: relative`) used across `src/` and `Concept_Demos/src/`.
- Don't add a second HTTP server in front of `src/api_bridge.py` — the bridge is intentionally stdlib-only.
- When changing routing / trust / memory behavior, update targeted tests first: `test_agent_routing.py`, `test_memory_bus.py`, `test_trust_interface.py`, `test_atp_validator.py`, `test_agent_registry.py`, `test_governance_monitor.py`.
- Prefer DI in tests (stub memory clients, temp SQLite paths) over requiring a live MCP server. Tests marked `requires_server` are explicitly opt-in.
- `Makefile` has stale targets that reference older paths/casing (e.g. `make run`, `make server` point at moved files). Verify a target before relying on it.
