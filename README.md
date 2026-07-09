# Artemis City
Artemis City is an agent-governance and memory-orchestration project built around three core ideas:

- structured agent communication through the Artemis Transmission Protocol (ATP)
- trust- and governance-aware task routing
- an Obsidian-backed memory layer with semantic recall
The repository is intentionally broader than a single service. It contains the authoritative Python orchestration core, API and dashboard surfaces, a standalone Obsidian MCP server, and a set of concept demos used to explore the platform’s behavior.

## Repository reality
New contributors should start with this mental model:

- `src/`  is the authoritative Python core.
- `app/`  contains HTTP and UI surfaces that sit on top of the Python core.
- `Concept_Demos/`  contains older but still useful prototype flows and walkthroughs.
- `src/Artemis Agentic Memory Layer/`  is a standalone TypeScript MCP server for Obsidian.
Some scripts and historical files still reflect earlier layouts. Prefer the paths documented below over older references in legacy notes.

This restructure phase follows the active `src/` plus `app/api` bridge architecture. It intentionally does not create `ts_service` or `python_service` directories; older alignment notes that proposed those layouts are historical context only.

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
    - ranks agents using a weighted composite score: alignment `0.4`  + accuracy `0.4`  + efficiency `0.2` 
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
    - `src/tests/conftest.py`  adds both the repo root and `Concept_Demos/src/`  to `sys.path`  so legacy modules remain importable in tests

### FastAPI dashboard backend (`app/api/main.py`)
This service exposes a dashboard-oriented API backed by the Python core and local SQLite databases.

Responsibilities:

- serves `/api/*`  endpoints for agents, tasks, reports, database views, and execution
- initializes the orchestrator when dependencies are available
- falls back to a SQLite-only mode when orchestration imports fail
- uses `X-API-Key`  authentication when configured
- reads environment from `app/api/.env` 
### TypeScript Express API (`app/api/index.ts`)
This is a separate TypeScript HTTP boundary.

Responsibilities:

- exposes `/api/v1/*`  endpoints for agents, registry, governance, memory, ATP, trust, and LLM features
- authenticates requests through Express middleware
- forwards Python-backed operations through `app/api/lib/pythonBridge.ts` 
- runs the bridge by spawning `python -m src.api_bridge` 
Supported external behavior is backed by bridge commands in `src/api_bridge.py`; routes exposed under `/api/v1` should update Python-owned state or read Python-owned stores.
### Dashboard and web-facing code (`app/web/frontend/`)
This directory currently contains mixed frontend and server-side TypeScript surfaces:

- `app/web/frontend/src/` 
    - React application source for dashboard pages such as Dashboard, Tasks, Reports, Agents, Database, and Executor
    - `vite.config.ts`  proxies `/api`  requests to `http://localhost:8000` , which matches the FastAPI dashboard backend

- `app/web/frontend/controllers/` , `middleware/` , and `v1/` 
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
- CLI walkthroughs such as `demo_artemis.py` , `demo_city_postal.py` , and `demo_memory_integration.py` 
- useful for exploring system concepts without standing up every service
## How the pieces interact
At a high level, the system works like this:

1. A user, API client, or demo submits a task or request.
2. The request reaches either the FastAPI service, the TypeScript API, or a demo script.
3. Python-backed execution routes into the orchestration core in `src/` .
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

- Python 3.12
- Node.js 18+ for TypeScript services
- Obsidian with the Local REST API plugin
- SQLite databases under `data/`  or `app/api/db/` 
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
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt
```
If you prefer to create the environment yourself, use `python3.12 -m venv .venv`
or `virtualenv --python python3.12 .venv`, then install packages with
`uv pip install`.

### 2. Configure environment files
The canonical provisioner is `./setup_secrets.sh`. It populates four
`.env` files with **one shared `MCP_API_KEY` across all of them**, plus
`FASTAPI_API_KEY` (root only, for the dashboard) and
`ARTEMIS_API_KEY_DEFAULT` (root + `app/api/.env`, for the TS Express
admin role):

```bash
./setup_secrets.sh              # sync: heal drift, generate what's missing
./setup_secrets.sh --check      # read-only; exits 1 if any consumer is out of sync
./setup_secrets.sh --regenerate # rotate ALL canonical keys (use after a leak)
```

Re-running is idempotent — existing values are preserved and propagated
to every file that declares them, so you can run `--check` from CI to
catch drift. Files written: `.env`, `app/api/.env`, `src/.env`, and
`src/Artemis Agentic Memory Layer/.env` (the last one is skipped if its
directory doesn't exist).

Other variables you'll want to set in `.env` after running the script:

- `OBSIDIAN_API_KEY` — from Obsidian → Settings → Local REST API
- `OBSIDIAN_VAULT_PATH` — only if your vault isn't at `<repo>/obsidian_vault`
- `OPENAI_API_KEY` / `ARTEMIS_EMBEDDING_API_KEY` — only if you use hosted embeddings
- `ARTEMIS_ENV` — `dev`/`staging`/`prod` selector

Never commit populated `.env` files (the root `.gitignore` already covers them).

### 3. Run the Python test suite
```bash
make test
```
### 4. Start the FastAPI dashboard backend
```bash
make api
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
│   ├── api/                         # FastAPI dashboard API + TS Express boundary
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
├── src/pyproject.toml
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
- The TypeScript API exposes versioned `/api/v1/*`  routes and shells out to the Python bridge for Python-backed operations.
- Express does not reimplement registry, memory, ATP, or trust logic in TypeScript. Exposed routes call `src/api_bridge.py` so state stays in Python-owned stores.
- The React client consumes `/api`  endpoints and is configured to proxy those requests to the FastAPI backend during development.
- The standalone Obsidian MCP server exposes vault operations over HTTP using bearer-style authentication.
### Package boundary
The wheel is scoped to the Python core packages (`src/`) and the kernel package (`app/kernel/`). Dashboard/API directories such as `app/api`, `app/web`, and `app/scripts` stay outside the wheel. The current `src/pyproject.toml` dependency list is still lock-style and includes dashboard/dev transitive packages; splitting that list into lean optional extras is tracked as follow-up packaging work.
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
- `Concept_Demos/README.md`  — demo-specific usage
- `src/Artemis Agentic Memory Layer/README.md`  — standalone MCP server setup and API details
- `AGENTS.md`  — project-specific contributor guidance
- `CLAUDE.md`  — implementation notes about the active code surfaces and bridge behavior
## License
This repository is licensed under the Apache License 2.0. See `LICENSE` for details.

---

# Technical Design Document: Artemis City
## Document Information
| Field | Value |
| ----- | ----- |
| **Project** | Artemis City |
| **Repository** | AgenticGovernace/AgenticGovernance-ArtemisCity |
| **Version** | 0.1.0 |
| **Status** | Alpha |
| **Last Updated** | 2025 |
---

## 1. Overview
### 1.1 Executive Summary
Artemis City is a multi-agent operating system designed for autonomous task orchestration with adaptive learning and governance. The system provides a comprehensive framework for coordinating AI agents through structured communication protocols, trust-aware task routing, and persistent memory management backed by an Obsidian vault.

### 1.2 Core Pillars
The platform is built around three foundational concepts:

1. **Artemis Transmission Protocol (ATP)** - Structured agent communication with standardized message formats
2. **Trust and Governance-Aware Task Routing** - Intelligent task assignment based on agent capabilities, trust scores, and Hebbian learning weights
3. **Obsidian-Backed Memory Layer** - Dual-store architecture combining explicit (Obsidian vault) and semantic (vector store) memory with write-through synchronization
### 1.3 System Identity
The project employs a "Living City" metaphor where:

- **Agents** are citizens with roles and clearances
- **Memory operations** are mail delivery handled by the postal service
- **The Obsidian vault** serves as city archives
- **Trust scores** function as citizen clearances
- **The kernel** acts as city hall coordinating all operations
---

## 2. Goals and Non-Goals
### 2.1 Goals
- **G1**: Provide a robust framework for multi-agent coordination with transparent governance
- **G2**: Implement adaptive learning through Hebbian weight management for agent-task associations
- **G3**: Maintain synchronized, auditable memory across explicit (Obsidian) and semantic (vector) stores
- **G4**: Enable trust-based access control with automatic violation tracking and quarantine
- **G5**: Support self-update governance with tiered approval workflows (auto/monitored/human)
- **G6**: Expose both Python and TypeScript API surfaces for flexible integration
- **G7**: Provide a standalone MCP server for Obsidian vault operations
### 2.2 Non-Goals
- **NG1**: Real-time streaming or WebSocket-based agent communication (current implementation uses synchronous polling)
- **NG2**: Distributed deployment across multiple nodes (single-instance architecture)
- **NG3**: Production-grade embedding models (uses deterministic hash-based stub embeddings)
- **NG4**: Full Obsidian plugin integration (relies on Local REST API plugin)
- **NG5**: Container orchestration for the main application (only standalone MCP server is containerized)
---

## 3. Architecture
### 3.1 High-Level Architecture
```
┌─────────────────────────────────────────────────────────────────────┐
│                        External Interfaces                          │
├─────────────────┬─────────────────┬─────────────────────────────────┤
│  FastAPI        │  TypeScript     │  CLI Entry Points               │
│  Dashboard API  │  Express API    │  (main.py, demos)               │
│  (port 8000)    │  (port 4000)    │                                 │
└────────┬────────┴────────┬────────┴─────────────────────────────────┘
         │                 │
         │    ┌────────────┴────────────┐
         │    │   Python Bridge         │
         │    │   (stdin/stdout JSON)   │
         │    └────────────┬────────────┘
         │                 │
┌────────┴─────────────────┴──────────────────────────────────────────┐
│                      Python Core (src/)                              │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │ Orchestrator│  │   Agent     │  │  Governance │                  │
│  │  (Kernel)   │◄─┤  Registry   │◄─┤   Layer     │                  │
│  └──────┬──────┘  └─────────────┘  └─────────────┘                  │
│         │                                                            │
│  ┌──────┴──────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │  Memory Bus │◄─┤   Hebbian   │  │   Sandbox   │                  │
│  │             │  │   Weights   │  │ Enforcement │                  │
│  └──────┬──────┘  └─────────────┘  └─────────────┘                  │
│         │                                                            │
│  ┌──────┴──────────────────┬────────────────────┐                   │
│  │                         │                    │                   │
│  ▼                         ▼                    ▼                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │  Obsidian   │  │   Vector    │  │   SQLite    │                  │
│  │   Manager   │  │   Store     │  │  Databases  │                  │
│  └─────────────┘  └─────────────┘  └─────────────┘                  │
└─────────────────────────────────────────────────────────────────────┘
```
### 3.2 Component Breakdown
#### 3.2.1 Orchestrator (Kernel)
**Location**: `src/mcp/orchestrator.py` 

The central coordinator managing agent task execution lifecycle:

```python
class Orchestrator:
def __init__(self):
    self.obs_manager = ObsidianManager(OBSIDIAN_VAULT_PATH)
    self.obs_parser = ObsidianParser()
    self.obs_generator = ObsidianGenerator()
    self.hebbian = HebbianWeightManager()
    self.vector_store = LocalVectorStore()
    self.governance_monitor = GovernanceMonitor()
    self.memory_bus = MemoryBus(...)
    self.agent_registry = AgentRegistry()
```
**Responsibilities**:

- Agent registration and lifecycle management
- Task routing based on required capabilities
- Task execution with memory enrichment
- Hebbian learning updates based on task outcomes
- Obsidian vault integration for task persistence
**Scoring Algorithm**:

```
Score = (Alignment × 0.4) + (Accuracy × 0.4) + (Efficiency × 0.2)
WeightedScore = Score × HebbianWeight(agent, task_type)
```
#### 3.2.2 Agent Registry
**Location**: `src/integration/agent_registry.py` 

SQLite-backed registry managing agent metadata, scores, and governance state:

```python
@dataclass
class AgentScore:
    alignment: float   # 0.0-1.0 policy adherence
    accuracy: float    # 0.0-1.0 output quality
    efficiency: float  # 0.0-1.0 speed/cost metric

    @property
    def composite_score(self) -> float:
        return self.alignment * 0.4 + self.accuracy * 0.4 + self.efficiency * 0.2
```
**Agent Registration Record**:

```json
{
  "agent_id": "uuid",
  "name": "string",
  "capabilities": ["string"],
  "alignment_score": 0.85,
  "accuracy_score": 0.92,
  "efficiency_score": 0.88,
  "status": "active|suspended|quarantined",
  "trust_tier": "auto|monitored|human",
  "violation_count": 0,
  "trust_score": 0.89
}
```
#### 3.2.3 Memory Bus
**Location**: `src/integration/memory_bus.py` 

Unified memory access layer implementing write-through synchronization:

```
┌─────────────────────────────────────────┐
│          Kernel / Agents                │
└────────────────┬────────────────────────┘
                 │ Read/Write
       ┌─────────▼─────────┐
       │   Memory Bus      │
       │  (Coordinator)    │
       └────┬──────────┬───┘
            │          │
      ┌─────▼─┐   ┌───▼─────┐
      │Obsidian│   │ Vector  │
      │ Store  │   │  Store  │
      └────────┘   └─────────┘
```
**Write Protocol**:

1. Write to vector store first (semantic indexing)
2. Write to Obsidian (primary/explicit storage)
3. Rollback vector write if Obsidian write fails
4. Record governance events on failure
**Read Hierarchy**:

1. **Exact Match**: Direct Obsidian lookup (<50ms p95)
2. **Keyword Match**: Obsidian metadata search (<150ms p95)
3. **Semantic Match**: Vector similarity search (<300ms p95)
#### 3.2.4 Hebbian Learning Layer
**Location**: `src/mcp/hebbian_weights.py` 

Adaptive connection weights between agents and task types:

```python
class HebbianWeightManager:
def strengthen_connection(self, origin: str, target: str) -> float:
    """ΔW = +1 for successful completion"""
    
def weaken_connection(self, origin: str, target: str) -> float:
    """ΔW = -1 for failure (minimum 0)"""
```
**Storage**: SQLite with atomic transactions
**Decay**: 5% every 30 days
**Pruning**: Connections with weight < 0.01 eligible for deletion

#### 3.2.5 Governance Framework
**Locations**:

- `src/governance/trust.py`  - Trust score computation
- `src/governance/approvals.py`  - Self-update approval tiers
- `src/governance/checkpoints.py`  - Checkpoint storage and rollback
- `src/integration/sandbox.py`  - Per-agent sandbox enforcement
**Trust Score Formula**:

```
TrustScore = SuccessRate × 0.35 
+ SecurityScore × 0.25 
+ CodeQuality × 0.20 
+ AuditApprovals × 0.15 
+ Uptime × 0.05
```
**Approval Tiers**:

| Tier | Trust Score | Conditions | Approval |
| ----- | ----- | ----- | ----- |
| Auto | ≥ 0.9 | < 1% code change, backwards-compatible | Automatic |
| Monitored | 0.7 - 0.9 | 1-10% change, new deps require review | Human approval |
| Human | < 0.7 | > 10% change, breaking changes, policy changes | Senior review |
**Sandbox Enforcement**:

- Tool whitelist per agent
- Path-based ACL with glob patterns
- 3-strike quarantine rule for violations
### 3.3 API Surfaces
#### 3.3.1 FastAPI Dashboard Backend
**Location**: `app/api/main.py`
**Port**: 8000

Serves dashboard-oriented endpoints with SQLite fallback mode:

| Endpoint | Method | Description |
| ----- | ----- | ----- |
| `/api/agents`  | GET | List registered agents |
| `/api/tasks`  | GET/POST | Task management |
| `/api/reports`  | GET | Agent report summaries |
| `/api/execute-task`  | POST | Execute specific task |
| `/api/db/hebbian/stats`  | GET | Hebbian network statistics |
| `/api/db/vectors/stats`  | GET | Vector store statistics |
| `/api/cli/execute`  | POST | CLI-style instruction execution |
**Authentication**: `X-API-Key` header

#### 3.3.2 TypeScript Express API
**Location**: `app/api/index.ts`
**Port**: 4000

Public HTTP boundary with Python bridge integration:

| Route | Description |
| ----- | ----- |
| `/api/v1/agents`  | Bridge-backed registry facade and agent status/mutation operations |
| `/api/v1/registry`  | Bridge-backed registry operations |
| `/api/v1/governance`  | Bridge-backed trust computation and update evaluation |
| `/api/v1/memory`  | Bridge-backed exact read, write, list, search, stats, and delete |
| `/api/v1/atp`  | Bridge-backed ATP parse, validate, queue, history, routing, format, and metadata |
| `/api/v1/trust`  | Bridge-backed trust score, permission, report, and Hebbian weight operations |
| `/api/v1/llm`  | LLM features |
#### 3.3.3 Python Bridge Protocol
**Location**: `src/api_bridge.py` (Python), `app/api/lib/pythonBridge.ts` (TypeScript)

JSON stdin/stdout transport between Express and Python core:

**Request Format**:

```json
{
  "command": "<namespace>.<action>",
  "payload": { ... }
}
```
**Response Format**:

```json
{ "ok": true, "data": { ... } }
{ "ok": false, "error": "...", "code": "..." }
```
**Available Commands**:

- `registry.list_agents` 
- `registry.get_agent` 
- `registry.get_violations` 
- `registry.clear_violations` 
- `registry.set_trust_tier` 
- `registry.record_violation` 
- `governance.compute_trust` 
- `governance.evaluate_update` 
---

## 4. Data Model
### 4.1 Database Schema
#### 4.1.1 Agent Registry (`data/agent_registry.db`)
```sql
CREATE TABLE agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    capabilities TEXT NOT NULL,  -- JSON array
    description TEXT,
    alignment REAL,
    accuracy REAL,
    efficiency REAL,
    trust_tier TEXT NOT NULL DEFAULT 'monitored',
    status TEXT NOT NULL DEFAULT 'active',
    violation_count INTEGER NOT NULL DEFAULT 0,
    quarantined_at TEXT,
    trust_score REAL,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE violations (
    violation_id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    violation_type TEXT NOT NULL,
    details TEXT NOT NULL,  -- JSON
    action_taken TEXT NOT NULL,
    cleared INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (agent_name) REFERENCES agents(name)
);
```
#### 4.1.2 Hebbian Weights (`data/hebbian_weights.db`)
```sql
CREATE TABLE node_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_node TEXT NOT NULL,
    target_node TEXT NOT NULL,
    weight REAL DEFAULT 0,
    activation_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_updated TEXT,
    created_at TEXT,
    UNIQUE(origin_node, target_node)
);
```
#### 4.1.3 Vector Store (`data/vector_store.db`)
```sql
CREATE TABLE vectors (
    doc_id TEXT PRIMARY KEY,
    embedding TEXT NOT NULL,  -- JSON array of floats
    metadata TEXT,            -- JSON object
    content TEXT
);
```
### 4.2 Obsidian Vault Structure
```
<vault_root>/
├── Agent Inputs/           # Pending task notes
│   └── *.md               # YAML frontmatter + markdown
├── Agent Outputs/          # Completed reports
│   └── *_Report_*.md      # Generated by agents
├── Postal/                 # Inter-agent mail
│   └── Agents/
│       └── <agent_name>/
├── Archives/               # Persistent storage
│   ├── Reflections/
│   ├── Reports/
│   ├── Policies/
│   └── Projects/
└── History/
    └── Delivery_Logs/
```
### 4.3 Task Note Format
```yaml
---
task_id: T123
agent: research_agent
required_capability: web_search
status: pending
tags: ["example", "research"]
---

# Task Title

Context: Description here
Keywords: keyword1, keyword2
Target: [[Some Other Note]]

## Subtasks
- [ ] Subtask 1
- [ ] Subtask 2
```
### 4.4 ATP Message Format
```
#Mode <direct|batch|stream|async>
#Context <context_id>
#Priority <critical|high|normal|low>
#ActionType <query|create|execute|...>
#TargetZone <kernel|registry|memory|sandbox|governance>
#SpecialNotes <notes>

<message_body>
```
---

## 5. API Design
### 5.1 Artemis Transmission Protocol (ATP)
#### 5.1.1 ATP Tags Specification
| Tag | Values | Required | Purpose |
| ----- | ----- | ----- | ----- |
| `#Mode`  | `direct`, `batch`, `stream`, `async`  | Yes | Communication mode |
| `#Context`  | UUID or string (max 64 chars) | Yes | Trace/correlation ID |
| `#Priority`  | `critical`, `high`, `normal`, `low`  | Yes | Queue priority |
| `#ActionType`  | See below | Yes | Operation type |
| `#TargetZone`  | `kernel`, `registry`, `memory`, `sandbox`, `governance`  | Yes | Target component |
| `#SpecialNotes`  | String (max 256 chars) | No | Metadata/hints |
#### 5.1.2 ActionType Values
**Query Operations**: `query`, `search`, `list`, `get_status`
**Modification Operations**: `create`, `update`, `delete`, `upsert`
**Execution Operations**: `execute`, `schedule`, `cancel`, `retry`
**Management Operations**: `register`, `revoke`, `approve`, `reject`
**Governance Operations**: `propose_update`, `rollback`, `override` 

### 5.2 REST API Endpoints
#### 5.2.1 Task Submission
```http
POST /api/v1/tasks
Content-Type: application/json

{
  "type": "text-analysis",
  "input": "Analyze the following document...",
  "required_capabilities": ["nlp", "sentiment-analysis"],
  "timeout_seconds": 300
}
```
**Response** (202 Accepted):

```json
{
  "task_id": "uuid",
  "status": "queued",
  "estimated_start": "2025-02-21T10:30:00Z"
}
```
#### 5.2.2 Memory Operations
**Write**:

```http
POST /api/v1/memory/write
Content-Type: application/json

{
  "operation": "write",
  "document": {
    "path": "path/to/document.md",
    "content": "# Heading\n\nContent...",
    "frontmatter": {
      "hebbian_weights": { "agent_uuid": 0.75 },
      "tags": ["tag1", "tag2"]
    }
  },
  "metadata": {
    "source_agent": "uuid",
    "conflict_resolution": "last_write_wins"
  }
}
```
**Semantic Search**:

```http
POST /api/v1/memory/search/semantic
Content-Type: application/json

{
  "query": "Find information about data processing",
  "top_k": 10,
  "filters": {
    "hebbian_weight_min": 0.3,
    "created_after": "2025-01-01T00:00:00Z"
  }
}
```
#### 5.2.3 Governance Operations
**Propose Update**:

```http
POST /api/v1/governance/updates
Content-Type: application/json

{
  "agent_id": "uuid",
  "update_type": "patch",
  "description": "Fix memory leak",
  "changes": {
    "files_modified": ["src/kernel.py"],
    "lines_added": 15,
    "lines_deleted": 8
  }
}
```
**Initiate Rollback**:

```http
POST /api/v1/governance/rollbacks
Content-Type: application/json

{
  "checkpoint_id": "uuid",
  "initiated_by": "admin_uuid",
  "reason": "error_detected"
}
```
### 5.3 Error Response Format
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": { "field": "specific errors" },
    "request_id": "uuid"
  }
}
```
**Common Error Codes**:

| Code | HTTP | Meaning |
| ----- | ----- | ----- |
| `INVALID_REQUEST`  | 400 | Malformed request |
| `NOT_FOUND`  | 404 | Resource not found |
| `CONFLICT`  | 409 | Write conflict |
| `RATE_LIMITED`  | 429 | Rate limit exceeded |
---

## 6. Security Considerations
### 6.1 Authentication
- **FastAPI Dashboard**: `X-API-Key`  header authentication
- **TypeScript Express API**: Bearer token in Authorization header
- **Python Bridge**: Process-level isolation (stdin/stdout)
### 6.2 Secret Management
Secrets are provisioned via `./setup_secrets.sh`:

| File | Consumer |
| ----- | ----- |
| `.env`  | Python core, FastAPI dashboard |
| `app/api/.env`  | TypeScript Express API |
| `src/.env`  | Memory-layer Python |
| `src/Artemis Agentic Memory Layer/.env`  | Standalone MCP server |
**Generated Keys**:

- `MCP_API_KEY`  - Shared across all components
- `FASTAPI_API_KEY`  - Dashboard only
- `ARTEMIS_API_KEY_DEFAULT`  - TS Express auth (key:role:perms tuple)
### 6.3 Sandbox Enforcement
```python
@dataclass
class ToolPolicy:
    name: str
    paths: List[str] = field(default_factory=list)  # glob patterns
    operations: List[str] = field(default_factory=list)

class AgentSandbox:
    def check_action(self, tool_name: str, path: str = None, 
                     operation: str = None) -> CheckResult:
        # Quarantined agents denied everything
        # Tool must be in whitelist
        # Path must match allowed patterns
        # Operation must be permitted
```
**Violation Types**:

- `unauthorized_tool` 
- `unauthorized_path` 
- `rate_limit` 
- `missing_capability` 
- `unsafe_network` 
**Quarantine Rule**: Auto-quarantine after 3 violations

### 6.4 Access Control
- Trust-based operation permissions (FULL/HIGH/MEDIUM/LOW/UNTRUSTED)
- Path-based ACLs for Obsidian vault operations
- Capability tags required for task routing
### 6.5 Audit Trail
All operations logged with:

- Timestamp
- Operation type
- Agent ID
- Content ID
- Status
- Latency
---

## 7. Testing Strategy
### 7.1 Test Pyramid
```
╱╲
        ╱  ╲        E2E Tests (10%)
       ╱────╲       - Full workflow validation
      ╱      ╲      - CLI interaction tests
     ╱────────╲
    ╱          ╲    Integration Tests (30%)
   ╱────────────╲   - Module interaction
  ╱              ╲  - ATP pipeline, Memory system
 ╱────────────────╲
╱                  ╲ Unit Tests (60%)
╲──────────────────╱ - Individual functions/classes
```
### 7.2 Coverage Requirements
| Module | Target |
| ----- | ----- |
| agents/artemis/ | 90% |
| agents/atp/ | 95% |
| core/instructions/ | 85% |
| memory/integration/ | 85% |
| **Overall** | **85%** |
### 7.3 Test Naming Convention
```
test_<module>_<function>_<scenario>
```
Examples:

- `test_atp_parser_parse_hash_format` 
- `test_trust_score_apply_decay_after_one_day` 
- `test_memory_client_get_context_server_unreachable` 
### 7.4 Running Tests
```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific markers
pytest -m unit
pytest -m integration
pytest -m e2e
```
### 7.5 CI Pipeline
GitHub Actions runs on `dev`, `staging`, `prod` branches:

- Environment configuration validation
- Python dependency installation
- Test suite execution (Python 3.12)
- Lint checks (ruff, flake8, mypy)
- Security scans (bandit, safety)
---

## 8. Rollout Plan
### 8.1 Environment Branching
| Branch | Environment | Purpose | Approvals |
| ----- | ----- | ----- | ----- |
| `dev`  | dev | Integration of feature work | 0 |
| `staging`  | staging | Pre-production rehearsal | 1 |
| `prod`  | prod | Production (default branch) | 2 |
**Promotion Flow**:

```
feature/* --PR--> dev --PR--> staging --PR--> prod
```
### 8.2 Configuration Management
Environment profiles in `config/environments/`:

- `dev.yaml` 
- `staging.yaml` 
- `prod.yaml` 
Selection via `ARTEMIS_ENV` environment variable.

### 8.3 Deployment Checklist
1. **Pre-deployment**:
    - [ ] All tests passing in CI
    - [ ] Security scans clean
    - [ ] Environment config validated
    - [ ] Checkpoint created

2. **Deployment**:
    - [ ] Promotion PR approved
    - [ ] Database migrations applied
    - [ ] Environment variables configured
    - [ ] Health checks passing

3. **Post-deployment**:
    - [ ] Smoke tests executed
    - [ ] Metrics baseline established
    - [ ] Rollback plan verified

### 8.4 Rollback Procedure
1. Identify checkpoint to restore
2. Verify checkpoint integrity (SHA-256 hash)
3. Initiate rollback via governance API
4. Restore registry state from checkpoint
5. Verify system health
6. Document incident
### 8.5 Monitoring
**Prometheus Metrics**:

```
artemis_memory_write_latency_ms
artemis_memory_read_latency_ms
artemis_memory_sync_lag_ms
artemis_memory_conflicts_detected
artemis_agent_execution_count
artemis_agent_success_rate
```
**Latency SLAs**:

| Operation | p50 | p95 | p99 |
| ----- | ----- | ----- | ----- |
| Task routing | 5ms | 15ms | 30ms |
| Memory write | 50ms | 200ms | 400ms |
| Memory read (exact) | 10ms | 50ms | 100ms |
| Memory read (vector) | 100ms | 300ms | 500ms |
---

## 9. Appendices
### 9.1 Repository Structure
```
.
├── app/
│   ├── api/                    # FastAPI + TypeScript API
│   ├── kernel/                 # In-process router
│   └── web/frontend/           # React dashboard
├── Concept_Demos/              # Prototype demos
├── config/environments/        # Environment configs
├── src/
│   ├── agents/                 # Agent implementations
│   ├── governance/             # Trust, approvals, checkpoints
│   ├── integration/            # Registry, memory bus, sandbox
│   ├── mcp/                    # Orchestrator, config, vector store
│   ├── obsidian_integration/   # Vault I/O
│   ├── tests/                  # Test suite
│   └── api_bridge.py           # TS-Python bridge
├── src/pyproject.toml
└── requirements.txt
```
### 9.2 Key Dependencies
| Package | Purpose |
| ----- | ----- |
| fastapi | Dashboard API |
| pydantic | Data validation |
| sqlite3 | Persistent storage |
| prometheus-client | Metrics |
| pyyaml | Configuration |
| python-dotenv | Environment loading |
### 9.3 Quick Start Commands
```bash
# Environment setup
./setup_secrets.sh
make install
make install-dev

# Development
make test
make lint
make check

# Running services
make run              # Python CLI
make server           # Obsidian MCP server
make frontend         # React dashboard
make api              # FastAPI
```
### 9.4 Related Documentation
| Document | Location |
| ----- | ----- |
| Architecture | `docs/ARCHITECTURE.md`  |
| Memory Bus | `docs/MEMORY_BUS.md`  |
| API Reference | `docs/API_REFERENCE.md`  |
| Test Plan | `docs/TEST_PLAN.md`  |
| Living City Metaphor | `docs/LIVING_CITY.md`  |
| Environments | `docs/ENVIRONMENTS.md`  |
| Security | <p>`SECURITY.md` </p><p></p><p> </p> |
