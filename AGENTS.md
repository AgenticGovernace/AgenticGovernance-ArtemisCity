# AGENTS.md

## Document Structure

This file contains two sections. The section titled "Implementation Notes for Artemis City" is the ACTIVE guidance. The preceding section ("Project Overview" through "Support and Documentation") is retained for historical context only and MUST NOT be followed when it conflicts with the Artemis City section.

Within this document, the "Implementation Notes for Artemis City" section (below the divider) supersedes all content above it when they conflict.

Section 1 (above the active-instructions divider) is LEGACY CONTEXT ONLY. Section 2 (below the divider) contains ALL active instructions. When editing code, follow ONLY Section 2.

If you cannot access an authoritative document referenced below, follow the instructions in this file as-is.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview (Legacy Context Only — Not Authoritative)

This is a Multi-Agent Coordination Platform (MCP) that integrates Python-based agents with an Obsidian vault. Agents can read tasks from Markdown notes, execute them, and write results back to the vault, creating a human-readable, persistent memory system.

## Architecture

### Core Components

**Three-Layer Architecture:**

1. **MCP Layer** (`src/mcp/`): Central orchestration
    - `orchestrator.py`: Coordinates agent lifecycle, task assignment, and Obsidian synchronization
    - `config.py`: System configuration loaded from `.env` file

2. **Obsidian Integration Layer** (`src/obsidian_integration/`): Vault I/O abstraction
    - `manager.py`: File system operations (read/write notes, list folders)
    - `parser.py`: Parses Markdown with YAML front matter into structured task data
    - `generator.py`: Generates formatted Markdown reports and task notes

3. **Agent Layer** (`src/agents/`): Extensible agent implementations
    - `base_agent.py`: Abstract base class defining `perform_task(task_context: dict) -> dict`
    - Concrete agents (e.g., `research_agent.py`, `summarizer_agent.py`) implement task logic

### Data Flow

1. Tasks are defined in Markdown notes in `Agent Inputs/` folder with YAML front matter
2. Orchestrator polls for `status: pending` tasks via `check_for_new_tasks_from_obsidian()`
3. Tasks are parsed, assigned to agents by name, and executed
4. Results are written to `Agent Outputs/` as formatted Markdown reports
5. Original task notes have their status updated (`in progress` → `completed`/`failed`)

### Task Note Format

Tasks use YAML front matter:

```yaml
---
task_id: T123
agent: research_agent
status: pending
tags: ["example"]
---

# Task Title
Context: Description here
Keywords: keyword1, keyword2
```

## Development Commands

### Environment Setup

```bash
# Install dependencies
# DEPRECATED — use `make install` in the active section below.
pip install -r requirements.txt

# Configure Obsidian vault path in .env
# DEPRECATED — use `./setup_secrets.sh` in the active section below.
echo "OBSIDIAN_VAULT_PATH=/path/to/your/vault" > .env
```

### Running the System

```bash
# Run the main orchestrator (polls for tasks and executes)
# DEPRECATED — use `make run` in the active section below.
python main.py
```

This will:

- Create `Agent Inputs/` and `Agent Outputs/` folders in the vault
- Generate an example task on first run
- Execute any pending tasks found in the input folder

## Adding New Agents

1. Create a new file in `src/agents/` (e.g., `my_agent.py`)
2. Inherit from `BaseAgent` and implement `perform_task(task_context: dict) -> dict`
3. Register in `orchestrator.py`:
   ```python
   self.agents = {
       "my_agent": MyAgent(),
       # existing agents...
   }
   ```
4. Create task notes with `agent: my_agent` in front matter

## Key Implementation Details

- **Agent Registration**: Agents are hardcoded in `Orchestrator.__init__()` dictionary
- **Task Polling**: Current implementation uses synchronous polling (no real-time triggering)
- **Status Updates**: Parser modifies YAML front matter in-place to track task state
- **Report Naming**: `{agent_name}_Report_{task_id}_{result_dict_length}.md`
- **Logging**: Centralized logger in `src/utils/helpers.py` writes to `mcp_obsidian.log`

## Configuration

Environment variables in `.env`:

- `OBSIDIAN_VAULT_PATH`: Absolute path to Obsidian vault (required)

Default folders (configured in `src/mcp/config.py`):

- `AGENT_INPUT_DIR = "Agent Inputs"`
- `AGENT_OUTPUT_DIR = "Agent Outputs"`

## Project Structure (Legacy Snapshot — Not Authoritative)

```
mcp_obsidian_system/
├── src/
│   ├── mcp/                      # Core MCP components (orchestration, config)
│   │   ├── __init__.py
│   │   ├── orchestrator.py       # The central coordinator of agents
│   │   └── config.py             # System-wide configuration
│   ├── agents/                   # Agent definitions
│   │   ├── __init__.py
│   │   ├── base_agent.py         # Abstract base class for all agents
│   │   ├── research_agent.py     # Example agent: reads, processes, writes
│   │   └── summarizer_agent.py   # Example agent: takes text, summarizes, writes
│   ├── obsidian_integration/     # Layer for Obsidian vault interaction
│   │   ├── __init__.py
│   │   ├── manager.py            # Handles direct file I/O with Obsidian vault
│   │   ├── parser.py             # Parses Markdown notes into structured data
│   │   └── generator.py          # Generates Markdown notes from structured data
│   └── utils/                    # Generic utility functions
│       ├── __init__.py
│       └── helpers.py            # Generic utility functions (e.g., logging)
├── main.py                       # Entry point for the MCP system
├── README.md                     # Explanation of the project
├── requirements.txt              # Python dependencies
└── .env                          # Environment variables (e.g., Obsidian vault path)
```

## How the System Works

### First Run Experience

When you run `main.py` for the first time:

1. Creates `Agent Inputs/` and `Agent Outputs/` folders in your Obsidian vault
2. Generates `Example Research Task.md` in `Agent Inputs/` with `status: pending`
3. Executes a direct task with the Summarizer Agent (demonstrates programmatic task assignment)
4. Scans for pending tasks in Obsidian and processes them
5. Writes reports to `Agent Outputs/` folder
6. Updates task status to `completed` or `failed`

### Obsidian-Triggered Workflow

1. Create a Markdown file in `<vault>/Agent Inputs/` with YAML front matter:
   ```yaml
   ---
   task_id: T_NEW_RESEARCH
   agent: research_agent
   status: pending
   ---

   # New Topic for Research

   Topic: The future of renewable energy technologies
   Context: Research emerging trends and key players.
   Keywords: solar, wind, geothermal, fusion
   ```

2. Run `python main.py` - the orchestrator will:
    - Detect the pending task
    - Update status to `in progress`
    - Assign to the specified agent
    - Execute the task
    - Write a report to `Agent Outputs/`
    - Update original note status to `completed`

### Direct Task Assignment (Code-Triggered)

You can also assign tasks programmatically in `main.py`:

```python
task_context = {
    "task_id": "T001",
    "title": "Summarize provided text",
    "content": "Your text here...",
    "agent": "summarizer_agent",
}
results = orchestrator.assign_and_execute_task("summarizer_agent", task_context)
```

## Detailed Component Documentation

### ObsidianManager (src/obsidian_integration/manager.py)

Handles all file system operations within the Obsidian vault:

- `read_note(relative_path: str) -> str | None`: Reads a note's content
- `write_note(relative_path: str, content: str, overwrite: bool = True)`: Writes/appends to notes
- `list_notes_in_folder(relative_folder_path: str, suffix: str = ".md") -> list[str]`: Lists all .md files in a folder
- `create_folder(relative_folder_path: str)`: Ensures a folder exists

All paths are relative to the vault root specified in `OBSIDIAN_VAULT_PATH`.

### ObsidianParser (src/obsidian_integration/parser.py)

Converts Markdown to structured data:

- `parse_task_note(content: str) -> dict | None`: Parses YAML front matter and content sections into task dictionary. Supports:
    - YAML front matter fields (task_id, agent, status, tags)
    - H1 headings as titles
    - Key-value pairs (e.g., `Context: Some text`)
    - Checkbox lists for subtasks

- `update_status_in_note(original_content: str, new_status: str, task_id: str = None) -> str`: Updates or adds status field in YAML front matter

### ObsidianGenerator (src/obsidian_integration/generator.py)

Creates formatted Markdown from structured data:

- `generate_agent_report(agent_name: str, task_id: str, results: dict) -> str`: Generates a report with:
    - YAML front matter (task_id, agent, timestamp, status, tags)
    - Summary section
    - Structured output of all result dictionary keys
    - Optional next steps checklist

- `generate_task_note(task_data: dict) -> str`: Creates a new task note from dictionary

### Orchestrator (src/mcp/orchestrator.py)

The central coordinator managing all agent operations:

**Key Methods:**

- `assign_and_execute_task(agent_name: str, task_context: dict, original_task_note_path: str = None) -> dict`:
    - Assigns task to agent
    - Executes via `agent.perform_task()`
    - Writes report to Obsidian
    - Updates original task status if path provided

- `check_for_new_tasks_from_obsidian() -> list[tuple[str, dict]]`:
    - Scans `AGENT_INPUT_DIR` for .md files
    - Parses each note
    - Returns list of (note_path, task_data) for `status: pending` tasks

- `update_task_status_in_obsidian(relative_note_path: str, new_status: str, task_id: str = None)`:
    - Updates status field in original task note

- `create_new_task_in_obsidian(task_data: dict, filename: str | None = None) -> str`:
    - Programmatically creates new task notes

### BaseAgent (src/agents/base_agent.py)

Abstract base class that all agents inherit from:

```python
class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = logger.getChild(self.name.replace(" ", "_"))

    @abstractmethod
    def perform_task(self, task_context: dict) -> dict:
        """Must return a dictionary with at minimum a 'summary' key"""
        pass

    def report_status(self, message: str):
        """Logs progress messages"""
        self.logger.info(message)
```

**Agent Implementation Pattern:**

```python
class MyAgent(BaseAgent):
    def __init__(self, name: str = "My Agent"):
        super().__init__(name)

    def perform_task(self, task_context: dict) -> dict:
        # Access task data
        topic = task_context.get('topic', 'unknown')
        context = task_context.get('context', '')

        # Report progress
        self.report_status(f"Starting work on {topic}...")

        # Do work here
        result = self._do_work(topic, context)

        # Return structured results
        return {
            "summary": "Brief overview of what was accomplished",
            "findings": ["Finding 1", "Finding 2"],
            "recommendations": ["Recommendation 1"],
            "custom_field": "Any custom data"
        }
```

### Example Agents

**ResearchAgent** (src/agents/research_agent.py):

- Simulates research activity with sleep delays
- Extracts topic, keywords, and depth from task context
- Returns findings, sources, and recommendations

**SummarizerAgent** (src/agents/summarizer_agent.py):

- Takes text from `content` field in task context
- Produces summary (currently simple truncation, ~20% of original)
- Returns original length, summary, and extracted main points

## Common Development Tasks

### Testing Agent Behavior

To test a single agent without Obsidian:

```python
from src.agents.research_agent import ResearchAgent

agent = ResearchAgent()
task_context = {
    "topic": "Test Topic",
    "keywords": "keyword1, keyword2",
    "depth": "overview"
}
results = agent.perform_task(task_context)
print(results)
```

### Debugging Task Parsing

To test how a note will be parsed:

```python
from src.obsidian_integration.parser import ObsidianParser

parser = ObsidianParser()
content = """---
task_id: T123
agent: research_agent
status: pending
---

# My Task
Context: Some context here
"""
task_data = parser.parse_task_note(content)
print(task_data)
```

### Creating Tasks Programmatically

Instead of manually creating Markdown files:

```python
orchestrator = Orchestrator()
task_data = {
    "task_id": "T_AUTO_001",
    "title": "Automated Task",
    "agent": "research_agent",
    "status": "pending",
    "context": "Research this topic",
    "keywords": "AI, ML"
}
path = orchestrator.create_new_task_in_obsidian(task_data)
print(f"Created task at: {path}")
```

## Tips for Development

### Logging

All components use centralized logging via `src/utils/helpers.py`:

- Logs to both console (StreamHandler) and file (`mcp_obsidian.log`)
- Agent-specific loggers are created via `logger.getChild(agent_name)`
- Use `self.report_status(message)` in agents for consistent logging

### Error Handling

Current implementation:

- File not found errors are logged as warnings
- Agent not found raises `ValueError`
- Task failures update status to `'failed'` in Obsidian
- Unhandled exceptions in tasks are caught in main loop and logged

### Task Status Lifecycle

```
pending → in progress → completed
                     → failed
                     → agent_not_found
```

Statuses are strings stored in YAML front matter and case-insensitive when checked.

### Extending the Parser

To support additional Markdown structures, modify `ObsidianParser.parse_task_note()`:

- Currently supports: YAML front matter, H1 titles, key-value pairs, checkbox lists
- Add custom parsing logic for tables, code blocks, embedded notes, etc.

### Virtual Environment

The project includes a `.venv/` directory. Activate it:

```bash
# macOS/Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

## Next Steps and Future Enhancements

### Real-Time Task Triggering

Current limitation: Synchronous polling requires manual runs of `main.py`.

**Solutions:**

1. **Obsidian Plugin**: Develop a custom plugin that sends webhooks when notes are created/modified with `status: pending`
2. **File Watcher**: Use `watchdog` library to monitor `Agent Inputs/` folder
3. **Scheduled Polling**: Run `main.py` on a cron job/scheduled task

### Asynchronous Processing

Current agents run synchronously, blocking the orchestrator.

**Enhancement:**

```python
import asyncio

class BaseAgent(ABC):
    @abstractmethod
    async def perform_task(self, task_context: dict) -> dict:
        pass

# In orchestrator
async def process_tasks():
    tasks = self.check_for_new_tasks_from_obsidian()
    await asyncio.gather(*[
        self.assign_and_execute_task(agent_name, task_data)
        for _, task_data in tasks
    ])
```

### More Robust Markdown Parsing

Current parser is regex-based and simple.

**Improvements:**

- Use `markdown-it-py` or `mistune` for proper AST parsing
- Support Obsidian-specific syntax:
    - `[[Wiki Links]]`
    - `![[Embedded Notes]]`
    - `#tags` and nested tags
    - Dataview queries
    - Block references `^block-id`

### Agent Communication

Enable multi-agent workflows where agents collaborate:

```python
# Agent A creates a task for Agent B
orchestrator.create_new_task_in_obsidian({
    "title": "Follow-up Research",
    "agent": "research_agent",
    "status": "pending",
    "context": f"Build on results from task {self.current_task_id}",
    "parent_task": self.current_task_id
})
```

### Dynamic Agent Registration

Instead of hardcoding agents in `Orchestrator.__init__()`:

```python
# Auto-discover agents in src/agents/
import importlib
import inspect

agents = {}
for file in Path("src/agents").glob("*_agent.py"):
    module = importlib.import_module(f"src.agents.{file.stem}")
    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and issubclass(obj, BaseAgent) and obj != BaseAgent:
            agent_instance = obj()
            agents[file.stem] = agent_instance
```

### Persistent Task Queue with Database

Move beyond filesystem-based task tracking:

```python
# Use SQLite or PostgreSQL
class TaskQueue:
    def enqueue(self, task_data: dict) -> str:
        """Add task to database, return task_id"""

    def get_pending_tasks(self) -> list[dict]:
        """Query for status='pending'"""

    def update_status(self, task_id: str, status: str):
        """Update task status"""
```

Still sync to Obsidian for human readability, but use DB as source of truth.

### Security Best Practices

When agents access external APIs:

1. **Never commit API keys**:
   ```python
   # In .env
   OPENAI_API_KEY=sk-...
   SERP_API_KEY=...

   # In agent
   api_key = os.getenv("OPENAI_API_KEY")
   ```

2. **Update .gitignore**:
   ```
   .env
   *.log
   __pycache__/
   .venv/
   ```

3. **Validate input from Obsidian notes** to prevent injection attacks if agents execute code/commands

### Web Dashboard

Create a Flask/FastAPI interface:

```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/tasks")
def get_tasks():
    return orchestrator.check_for_new_tasks_from_obsidian()

@app.post("/tasks")
def create_task(task_data: dict):
    return orchestrator.create_new_task_in_obsidian(task_data)

@app.get("/agents")
def list_agents():
    return list(orchestrator.agents.keys())
```

### Error Handling Improvements

Add retry logic and more granular error tracking:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

class ResilientAgent(BaseAgent):
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def perform_task(self, task_context: dict) -> dict:
        # Task logic with automatic retries on failure
        pass
```

Track errors in reports:

```python
{
    "summary": "Task failed",
    "error": str(exception),
    "error_type": exception.__class__.__name__,
    "stack_trace": traceback.format_exc(),
    "retry_count": 3
}
```

## Support and Documentation

- Project documentation is primarily in this CLAUDE.md file
- Additional context in `README.md` and `Plan.md.md`
- Code is documented with docstrings
- Log files in `mcp_obsidian.log` provide runtime debugging information


---

# ⚠️ ACTIVE INSTRUCTIONS BEGIN HERE — everything above is legacy context only and must not be followed when it conflicts.

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
win**. Within this document, this Artemis City section supersedes all
content above it. If an authoritative document is unavailable, follow this
file as-is.

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
