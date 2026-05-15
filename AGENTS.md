# AGENTS.md

## Start Here (Repo Reality)
- Treat `Concept_Demos/src/` as the primary implementation surface for orchestrator/agents/memory (`mcp/orchestrator.py`, `integration/memory_bus.py`, `agents/*`).
- Test- Root `integration/` also contains MCP-facing utilities (`integration/memory_client.py`, `integration/context_loader.py`, `integration/trust_interface.py`) that are imported directly by tests.
  s intentionally bridge both trees via `tests/conftest.py` (`sys.path` inserts project root and `Concept_Demos/src`). Avoid moving modules without updating test import assumptions.

## Big-Picture Architecture (What Talks to What)
- Orchestration center: `Concept_Demos/src/mcp/orchestrator.py` wires `AgentRegistry`, `MemoryBus`, `GovernanceMonitor`, `HebbianWeightManager`, and `LocalVectorStore`.
- Routing: `AgentRegistry.route_task()` picks highest composite score (`alignment*0.4 + accuracy*0.4 + efficiency*0.2`) among agents with matching `required_capability`.
- Memory write path: `MemoryBus.write_note_with_embedding()` writes vector store first, then Obsidian note; on file-write failure it rolls back vector insert.
- Memory read path: `MemoryBus.read()` uses exact note lookup -> keyword scan of configured dirs -> vector query fallback.
- Trust gate: `integration/trust_interface.py` controls allowed ops (`read/write/delete/...`) by trust level; `integration/postal_service.py` checks trust before archive/mail writes.

## Protocol and Message Conventions (Project-Specific)
- ATP is a first-class protocol (`Concept_Demos/src/agents/atp/*`): Mode/Context/ActionType are the minimum "complete" header set.
- `ATPValidator` default is lenient (`strict=False`): missing headers produce warnings/suggestions, not hard failures unless strict mode is enabled.
- Keep `TargetZone` path-like and preferably absolute/home-relative; validator suggests improvements for ambiguous values.
- Existing fixtures show accepted header styles: `#Mode: Build` and `[[Mode]]: Review` (`tests/conftest.py`).

## Developer Workflows That Matter
- Python tests are under `tests/`; `tests/pytest.ini` defines markers (`unit`, `integration`, `requires_server`, etc.).
- Common local test command: `python3 -m pytest tests/ -v` (or focused files during iteration).
- If `pytest` is missing, install deps first (`pip install -r requirements.txt`) before assuming test failures are code-related.
- Web surfaces are independent packages: `web/api` (Express/TypeScript) and `web/frontend` (React/Vite); run `npm install && npm run build` in each when touching web code.
- `Makefile` has useful shortcuts but some targets reference older paths/casing; verify target commands before relying on them blindly.

## Integration Points and External Dependencies
- MCP server contract is HTTP POST to `/api/<operation>` and GET `/health` (`integration/memory_client.py`); operation names are in `MCPOperation`.
- `MemoryClient` requires `MCP_API_KEY`; default base URL is `http://localhost:3000`.
- Obsidian integration depends on vault path from `OBSIDIAN_VAULT_PATH` (`Concept_Demos/src/mcp/config.py`) and local REST settings in `.env`/`.env.example`.
- Vector persistence is SQLite-backed (`Concept_Demos/src/mcp/vector_store.py`, default `data/vector_store.db`) with deterministic local embeddings for offline tests.

## Safe Change Patterns in This Repo
- Preserve import duality patterns (`try: absolute import ... except ImportError: relative import ...`) used across `Concept_Demos/src` modules.
- Prefer dependency injection in tests (stub/mocked memory clients, temp SQLite paths) instead of requiring running servers.
- When changing routing/trust/memory behavior, update the matching targeted tests first (`tests/test_agent_routing.py`, `tests/test_memory_bus.py`, `tests/test_trust_interface.py`, `tests/test_atp_validator.py`).
- Keep user-facing strings and status dict shape stable (`{"status": "success|failed", ...}`) because tests assert these exact contracts.

