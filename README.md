from . import kernelfrom . import kernel# Artemis City

Artemis City is an agent-governance and memory-orchestration project built around three core ideas:

- structured agent communication through the Artemis Transmission Protocol (ATP)
- trust- and governance-aware task routing
- an Obsidian-backed memory layer with semantic recall

The repository is intentionally broader than a single service. It contains the authoritative Python orchestration core, API and dashboard surfaces, a standalone Obsidian MCP server, and a set of concept demos used to explore the platform’s behavior.

## Repository reality

New contributors should start with this mental model:

- `src/` is the authoritative Python core.
- `app/` contains HTTP and UI surfaces that sit on top of the Python core.
- `Concept_Demos/` contains older but still useful prototype flows and walkthroughs.
- `src/Artemis Agentic Memory Layer/` is a standalone TypeScript MCP server for Obsidian.

Some scripts and historical files still reflect earlier layouts. Prefer the paths documented below over older references in legacy notes.

## Core components

### Python orchestration core (`src/`)

This is the main implementation surface for orchestration, governance, memory, and tests.

Key modules:

- `src/mcp/orchestrator.py`
  - central coordinator for task execution
  - initializes the Obsidian manager, parser/generator utilities, Hebbian weights, governance monitor, vector store, memory bus, and agent registry
  - registers built-in agents and routes work to the best match
- `src/integration/agent_registry.py`
  - stores agent metadata and scores
  - ranks agents using a weighted composite score: alignment `0.4` + accuracy `0.4` + efficiency `0.2`
  - tracks trust tiers, violation counts, and quarantine state
- `src/integration/memory_bus.py`
  - write-through memory layer shared by the orchestrator
  - writes to the vector store first, then to Obsidian
  - rolls back the vector write if the Obsidian write fails
  - reads via exact note lookup, keyword scan, then vector fallback
- `src/integration/trust_interface.py`
  - models trust levels and reinforcement/decay
  - gates operations based on trust level
- `src/api_bridge.py`
  - JSON stdin/stdout bridge used by the TypeScript API layer to invoke Python operations without embedding a Python web framework inside the core
- `src/tests/`
  - primary Python test suite
  - `src/tests/conftest.py` adds both the repo root and `Concept_Demos/src/` to `sys.path` so legacy modules remain importable in tests

### FastAPI dashboard backend (`app/api/main.py`)

This service exposes a dashboard-oriented API backed by the Python core and local SQLite databases.

Responsibilities:

- serves `/api/*` endpoints for agents, tasks, reports, database views, and execution
- initializes the orchestrator when dependencies are available
- falls back to a SQLite-only mode when orchestration imports fail
- uses `X-API-Key` authentication when configured
- reads environment from `app/api/.env`

### TypeScript Express API (`app/api/index.ts`)

This is a separate TypeScript HTTP boundary.

Responsibilities:

- exposes `/api/v1/*` endpoints for agents, registry, governance, memory, ATP, trust, and LLM features
- authenticates requests through Express middleware
- forwards Python-backed operations through `app/api/lib/pythonBridge.ts`
- runs the bridge by spawning `python -m src.api_bridge`

### Dashboard and web-facing code (`app/web/frontend/`)

This directory currently contains mixed frontend and server-side TypeScript surfaces:

- `app/web/frontend/src/`
  - React application source for dashboard pages such as Dashboard, Tasks, Reports, Agents, Database, and Executor
  - `vite.config.ts` proxies `/api` requests to `http://localhost:8000`, which matches the FastAPI dashboard backend
- `app/web/frontend/controllers/`, `middleware/`, and `v1/`
  - additional TypeScript controllers and demo API routes used for agent, memory, ATP, trust, and LLM workflows

Important note: this tree is still in transition. The checked-in package scripts are not a perfect reflection of the React/Vite client structure, so treat it as a mixed client/server workspace rather than a fully isolated frontend package.

### Obsidian MCP server (`src/Artemis Agentic Memory Layer/`)

This is a standalone TypeScript service that exposes an Obsidian vault over HTTP for agent workflows.

Responsibilities:

- authenticates API requests with `MCP_API_KEY`
- translates REST calls into Obsidian Local REST API operations
- provides note read/write/search/update/delete and related utility endpoints
- supports local development and Docker-based deployment

Use this when you want a dedicated MCP-style memory service independent of the main Python orchestration runtime.

### Concept demos (`Concept_Demos/`)

These are prototype assets and walkthroughs used to demonstrate ATP, memory, routing, and Hebbian behavior.

Highlights:

- browser demos served as static HTML
- CLI walkthroughs such as `demo_artemis.py`, `demo_city_postal.py`, and `demo_memory_integration.py`
- useful for exploring system concepts without standing up every service

## How the pieces interact

At a high level, the system works like this:

1. A user, API client, or demo submits a task or request.
2. The request reaches either the FastAPI service, the TypeScript API, or a demo script.
3. Python-backed execution routes into the orchestration core in `src/`.
4. The orchestrator asks the agent registry to choose the best agent for the requested capability.
5. The selected agent reads or writes context through the memory bus.
6. The memory bus keeps explicit Obsidian notes and semantic vector memory in sync.
7. Governance and trust layers observe execution quality, allowed operations, and failure streaks.
8. Results flow back through the same API or CLI surface that initiated the work.

## Deployment and runtime model

### Environment selection

Environment profiles live in `config/environments/`:

- `dev.yaml`
- `staging.yaml`
- `prod.yaml`

`ARTEMIS_ENV` selects which profile is active. CI validates all three environment files.

### External dependencies

Depending on which surface you run, the repository may depend on:

- Python 3.10+
- Node.js 18+ for TypeScript services
- Obsidian with the Local REST API plugin
- SQLite databases under `data/` or `app/api/db/`
- optional local inference services such as Exo

### Containerization

Containerization is currently focused on the standalone Obsidian MCP server:

- `src/Artemis Agentic Memory Layer/Dockerfile`
- `src/Artemis Agentic Memory Layer/docker-compose.yml`

The root repository itself is not organized around a single top-level Docker deployment.

## Quick start

### 1. Set up the Python environment

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
pip install -r requirements-dev.txt
```

If you prefer not to install the package in editable mode, the repo also includes `requirements.txt` and `requirements-dev.txt` for direct pip installs.

### 2. Configure environment files

Copy the examples you need:

```bash
cp .env.example .env
cp app/api/.env.example app/api/.env
cp "src/Artemis Agentic Memory Layer/.env.example" "src/Artemis Agentic Memory Layer/.env"
```

Important variables include:

- `ARTEMIS_ENV`
- `MCP_BASE_URL`
- `MCP_API_KEY`
- `OBSIDIAN_BASE_URL`
- `OBSIDIAN_API_KEY`
- `OBSIDIAN_VAULT_PATH`
- `FASTAPI_API_KEY`

Never commit populated `.env` files.

### 3. Run the Python test suite

```bash
python -m pytest src/tests
```

### 4. Start the FastAPI dashboard backend

```bash
uvicorn app.api.main:app --reload --port 8000
```

This matches the proxy target configured in `app/web/frontend/vite.config.ts`.

### 5. Start the standalone Obsidian MCP server (optional)

```bash
cd "src/Artemis Agentic Memory Layer"
npm install
npm run dev
```

Or run it with Docker:

```bash
cd "src/Artemis Agentic Memory Layer"
docker-compose up --build
```

## Common developer workflows

### Run core quality checks

```bash
make check
```

This runs formatting checks, import sorting checks, Flake8, and MyPy.

### Run security checks

```bash
make security
```

### Run demos

```bash
python Concept_Demos/demo_artemis.py
python Concept_Demos/demo_city_postal.py
python Concept_Demos/demo_memory_integration.py
```

### Serve browser demos

```bash
cd Concept_Demos
python3 -m http.server 8080
```

Then open `http://localhost:8080`.

## Repository map

```text
.
├── app/
│   ├── api/                         # FastAPI dashboard API + TypeScript API surface
│   └── web/frontend/               # React dashboard source + additional TS routes/controllers
├── Concept_Demos/                  # Browser demos and CLI walkthroughs
├── config/environments/            # dev / staging / prod environment profiles
├── src/
│   ├── agents/                     # Python agent implementations
│   ├── integration/                # Registry, memory bus, governance, trust interfaces
│   ├── mcp/                        # Orchestrator, config, vector store, Hebbian logic
│   ├── obsidian_integration/       # Obsidian manager/parser/generator helpers
│   ├── tests/                      # Primary Python tests
│   ├── api_bridge.py               # JSON bridge for TS-to-Python calls
│   └── Artemis Agentic Memory Layer/  # Standalone TypeScript MCP server
├── .env.example
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

## Runtime behavior details

### Orchestrator initialization

When the Python core starts, the orchestrator:

- creates the Obsidian manager, parser, and generator
- initializes Hebbian weights and the local vector store
- creates the governance monitor and memory bus
- registers built-in agents in the agent registry
- ensures agent input/output folders exist in the vault

### Request handling

- FastAPI serves dashboard-oriented endpoints and can operate in a fallback mode when the full orchestrator cannot be imported.
- The TypeScript API exposes versioned `/api/v1/*` routes and shells out to the Python bridge for Python-backed operations.
- The React client consumes `/api` endpoints and is configured to proxy those requests to the FastAPI backend during development.
- The standalone Obsidian MCP server exposes vault operations over HTTP using bearer-style authentication.

### Error handling and governance

- trust and governance metadata are stored alongside agent registry data
- repeated violations can quarantine an agent
- memory writes are designed to avoid divergence between semantic and explicit storage
- fallback behavior exists in the FastAPI layer when orchestration dependencies are unavailable

## CI and branch model

GitHub Actions CI runs on the `dev`, `staging`, and `prod` branches.

The current workflow validates:

- environment configuration files
- Python dependency installation
- the Python test suite in `src/tests`

## Suggested entry points for new contributors

If you are new to the repo, start in this order:

1. `src/mcp/orchestrator.py`
2. `src/integration/agent_registry.py`
3. `src/integration/memory_bus.py`
4. `src/integration/trust_interface.py`
5. `app/api/main.py`
6. `app/api/index.ts`
7. `Concept_Demos/README.md`
8. `src/Artemis Agentic Memory Layer/README.md`

That path gives you the orchestration core first, then the public API surfaces, then the demo and standalone memory-server layers.

## Additional documentation

- `Concept_Demos/README.md` — demo-specific usage
- `src/Artemis Agentic Memory Layer/README.md` — standalone MCP server setup and API details
- `CLAUDE.md` / `AGENTS.md` — implementation notes on the active code surfaces and bridge behavior (byte-for-byte mirrors: `CLAUDE.md` for Claude, `AGENTS.md` for other coding agents)
- `docs/TEST_PLAN.md` — test strategy, coverage targets, and test-naming conventions

## License

This repository is licensed under the Apache License 2.0. See `LICENSE` for details.
