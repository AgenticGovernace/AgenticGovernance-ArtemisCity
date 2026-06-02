# XMCP (Multi-Agent Coordination Platform) - Project Documentation

XMCP (Multi-Agent Coordination Platform) - Project Documentation

## Overview
MCP is a sophisticated **multi-agent orchestration system** that coordinates autonomous agents to perform specialized tasks. It features intelligent task routing, semantic memory integration with Obsidian, Hebbian learning for adaptive routing, and a complete React web interface.

**Architecture**: Hybrid Python backend (FastAPI) + React/TypeScript frontend with Obsidian vault integration.

---

## Project Structure
```
MCP/
├── main.py                          # CLI entry point
├── requirements.txt                 # Python dependencies
├── package.json                     # Root npm config
│
├── src/
│   ├── agents/                      # Agent implementations
│   │   ├── base_agent.py           # Abstract base class
│   │   ├── artemis_agent.py        # System management agent
│   │   ├── research_agent.py       # Web search/research agent
│   │   ├── summarizer_agent.py     # Text summarization agent
│   │   └── artemis/                # Artemis-specific modules
│   │       ├── persona.py          # Personality & response modes
│   │       ├── reflection.py       # Concept graph & synthesis
│   │       └── semantic_tagging.py # Semantic extraction
│   │
│   ├── mcp/                         # Core MCP system
│   │   ├── orchestrator.py         # Central task coordinator
│   │   ├── config.py               # Configuration & env vars
│   │   ├── vector_store.py         # Semantic search engine
│   │   └── hebbian_weights.py      # Neural-inspired learning
│   │
│   ├── integration/                 # Integration layers
│   │   ├── agent_registry.py       # Agent registry & routing
│   │   ├── memory_bus.py           # Hybrid memory system
│   │   └── governance.py           # Failure tracking & alerts
│   │
│   ├── obsidian_integration/        # Obsidian vault integration
│   │   ├── manager.py              # File system interface
│   │   ├── parser.py               # Markdown task parser
│   │   └── generator.py            # Markdown generator
│   │
│   ├── utils/                       # Utilities
│   │   ├── helpers.py              # Logger & helpers
│   │   └── run_logger.py           # Execution logging
│   │
│   ├── types.py                     # Type definitions (TaskContext, TaskResult)
│   └── exceptions.py                # Exception hierarchy
│
├── web/
│   ├── api/
│   │   └── main.py                 # FastAPI backend (port 8000)
│   │
│   └── frontend/
│       ├── src/
│       │   ├── App.tsx             # Main app component
│       │   ├── main.tsx            # React entry point
│       │   ├── api.ts              # API client
│       │   ├── components/
│       │   │   └── Layout.tsx      # Navigation & routing
│       │   └── pages/
│       │       ├── Dashboard.tsx   # Landing page
│       │       ├── Tasks.tsx       # Task management
│       │       ├── Reports.tsx     # Report viewer
│       │       └── Agents.tsx      # Agent listing
│       ├── package.json
│       ├── vite.config.ts
│       ├── tsconfig.json
│       └── eslint.config.js
│
├── data/                            # SQLite databases & logs
│   ├── agent_registry.db           # Agent metadata
│   ├── hebbian_weights.db          # Learning connections
│   ├── vector_store.db             # Semantic embeddings
│   ├── run_logs.db                 # Execution metrics
│   └── governance_events.log       # Sync failure tracking
│
├── logs/                            # Run execution logs (markdown format)
│   └── run_*.md
│
└── tests/                           # Test suite
    ├── test_agent_routing.py
    ├── test_hebbian_learning.py
    ├── test_memory_bus.py
    └── test_base_agent_compliance.py
```
---

## Core Components
### 1. **Orchestrator** (`src/mcp/orchestrator.py`)
The central coordination hub that:

- Manages agent lifecycle and registration
- Routes tasks to appropriate agents
- Enriches tasks with semantic memory
- Updates Hebbian learning weights
- Manages Obsidian vault integration
- Tracks execution metrics
  **Key Methods**:

- `route_and_execute_task(task_data, note_path=None)`  - Auto-route task to best agent
- `assign_and_execute_task(agent_name, task_data, note_path)`  - Assign to specific agent
- `check_for_new_tasks_from_obsidian()`  - Discover pending tasks
- `create_new_task_in_obsidian(task_data)`  - Create task note
- `_enrich_task_with_memory(task_data)`  - Pull contextual memory
### 2. **Agents**
All agents inherit from `BaseAgent` and implement `perform_task(context)`.

#### **Artemis Agent** (`src/agents/artemis_agent.py`)
- **Capabilities**: `system_management` , `agent_coordination`
- **Purpose**: System oversight, architectural analysis, context integration
- **Components**:
    - **ArtemisPersona** (`artemis/persona.py` ): Personality traits, response modes (reflective, architectural, conversational, technical, poetic)
    - **ReflectionEngine** (`artemis/reflection.py` ): Concept graph building, pattern recognition
    - **SemanticTagger** (`artemis/semantic_tagging.py` ): Semantic tag extraction

- **Output**: Structured result with narrative, semantic tags, persona context
#### **Research Agent** (`src/agents/research_agent.py`)
- **Capabilities**: `web_search` , `document_analysis`
- **Purpose**: Information gathering and analysis
- **Output**: Research findings with sources
#### **Summarizer Agent** (`src/agents/summarizer_agent.py`)
- **Capabilities**: `text_summarization`
- **Purpose**: Content summarization
- **Algorithm**: Extracts key points from text
- **Output**: Summary, original metrics, extracted points
### 3. **Agent Registry** (`src/integration/agent_registry.py`)
Manages agent discovery and intelligent task routing:

- **Storage**: SQLite (`data/agent_registry.db` )
- **Scoring**: Composite score = alignment(0.4) + accuracy(0.4) + efficiency(0.2)
- **Methods**:
    - `register_agent(agent)`  - Add agent to system
    - `route_task(task_data)`  - Find best agent for capability
    - `update_score(agent_name, alignment, accuracy, efficiency)`  - Update performance

### 4. **Memory Bus** (`src/integration/memory_bus.py`)
Hybrid semantic + explicit memory system:

- **Write Protocol**: Write to vector store → persist to Obsidian (write-through)
- **Read Hierarchy**: Exact lookup → keyword scan → semantic similarity search
- **Metrics** (Prometheus): Write latency, read counts, sync lag
- **Methods**:
    - `write_note_with_embedding(path, content, metadata)`  - Store with embedding
    - `read_note(path)`  - Retrieve note content
    - Automatic syncing between vector store and Obsidian

### 5. **Vector Store** (`src/mcp/vector_store.py`)
Semantic search engine:

- **Database**: SQLite (`data/vector_store.db` )
- **Embedding**: Deterministic hash-bucketed character n-grams (16 dimensions)
- **Similarity**: Cosine similarity in Python
- **Methods**:
    - `upsert(doc_id, embedding, content, metadata)`  - Store/update vector
    - `search(query_vector, top_k=5)`  - Semantic search

### 6. **Hebbian Learning** (`src/mcp/hebbian_weights.py`)
Neural-inspired learning for agent-task associations:

- **Database**: SQLite (`data/hebbian_weights.db` )
- **Update Rules**:
    - Success: Weight += 1 (strengthen connection)
    - Failure: Weight -= 1 (weaken connection)

- **Methods**:
    - `strengthen_connection(origin, target)`  - Increase weight on success
    - `weaken_connection(origin, target)`  - Decrease weight on failure
    - `get_network_summary()`  - Network statistics

### 7. **Governance Monitor** (`src/integration/governance.py`)
Tracks memory bus failures and triggers alerts:

- **Log**: `data/governance_events.log`  (JSONL format)
- **Threshold**: Alert after 3 consecutive failures
- **Methods**:
    - `record_failure()`  - Log sync failure
    - `record_success()`  - Reset failure streak
    - `get_failure_streak()`  - Current failure count

### 8. **Obsidian Integration**
**ObsidianManager** (`src/obsidian_integration/manager.py`):

- File system interface to Obsidian vault
- **Directories**: `Agent Inputs`  (tasks), `Agent Outputs`  (reports)
- **Methods**: `read_note()` , `write_note()` , `list_notes_in_folder()`
## **ObsidianParser** (`src/obsidian_integration/parser.py`):
- Parses markdown task notes with YAML frontmatter
- **Expected Format**:
 ```yaml
##  task_id: T001
 required_capability: web_search
 status: pending
# Task Title
 Content here...

```
**ObsidianGenerator** (`src/obsidian_integration/generator.py`):
- Generates formatted markdown for tasks and reports

---

## Task Execution Flow
```
1. Task Discovery
    - CLI instruction (-i flag)
    - OR Obsidian vault (Agent Inputs folder)
    - OR Web UI request

2. Task Routing
    - Orchestrator.route_and_execute_task()
    - AgentRegistry finds agent with required_capability
    - Select agent with highest composite score

3. Task Enrichment
    - MemoryBus.read() pulls contextual memory
    - VectorStore semantic search for related info

4. Task Execution
    - Agent.perform_task(enriched_context)
    - Async execution with logging

5. Memory Persistence
    - MemoryBus.write_note_with_embedding()
    - Vector store insertion (semantic)
    - Obsidian file write (explicit)
    - Governance monitor tracks sync

6. Learning Update
    - Hebbian weights adjust based on success/failure
    - Agent scores updated in registry
    - Metrics logged to run_logs.db

7. Status Update
    - Task status updated to "completed"/"failed" in Obsidian
    - Results returned to caller

```
---

## Running the Application

### Start Everything (CLI + Web UI)
```bash
npm start
```
This runs concurrently:

- `uvicorn web.api.main:app --reload --port 8000`  (FastAPI backend)
- `cd web/frontend && npm run dev`  (React dev server)
### CLI Only
```bash
python main.py [options]
```
**Options**:

- `-i, --instruction TEXT`  - Send instruction to agent
- `-c, --capability TEXT`  - Specify required capability
- `--agent TEXT`  - Explicit agent name
- `-t, --title TEXT`  - Task title
- `--skip-demos`  - Skip demo content creation
- `--show-hebbian`  - Display Hebbian network stats
- `--agent-stats AGENT`  - Show specific agent statistics
### Examples
```bash
# Direct instruction
python main.py -i "Research the latest developments in AI" -c web_search

# Assign to specific agent
python main.py --agent artemis_agent -i "Analyze system architecture"

# Show Hebbian learning stats
python main.py --show-hebbian
```
---

## Web Interface
### Frontend (React)
- **Port**: 3000 (dev server via Vite)
- **URL**: [http://localhost:3000](http://localhost:3000/)
  **Pages**:

- **Dashboard** (`/` ) - Landing page with system overview
- **Tasks** (`/tasks` ) - Create, view, execute tasks
- **Reports** (`/reports` ) - View task execution reports
- **Agents** (`/agents` ) - List agents and their capabilities
### Backend API (FastAPI)
- **Port**: 8000
- **Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)  (Swagger UI)
  **Endpoints**:

- `GET /api/agents`  - List registered agents
- `GET /api/tasks`  - Get pending tasks from Obsidian
- `POST /api/tasks`  - Create new task
- `POST /api/tasks/{task_id}/execute`  - Execute specific task
- `POST /api/tasks/execute-all`  - Batch execute all tasks
- `GET /api/reports`  - List generated reports
- `GET /api/reports/{filename}`  - Get report details
---

## Configuration
**Environment Variables** (`.env`):

```
OBSIDIAN_VAULT_PATH=/path/to/your/obsidian/vault
```
**Agent Input/Output Directories**:

- Input: `{VAULT_PATH}/Agent Inputs`  - Where agents discover new tasks
- Output: `{VAULT_PATH}/Agent Outputs`  - Where agents write reports
---

## Database Schema
| Database | Tables | Purpose |
| ----- | ----- | ----- |
|  |  | Agent metadata, capabilities, performance scores |
|  |  | Agent-task associations, learning weights |
|  |  | Semantic embeddings for memory recall |
|  | <p></p><p></p><p></p> | Execution metrics and timing |
---

## Technology Stack
**Backend**:

- Python 3.8+
- FastAPI (REST API framework)
- Uvicorn (ASGI server)
- SQLite3 (persistence)
- Optional: Prometheus (metrics)
  **Frontend**:

- React 19
- TypeScript
- Chakra UI (component library)
- React Router v6 (routing)
- Vite (bundler)
- ESLint (linting)
  **Infrastructure**:

- Node.js/npm (frontend tooling)
- Obsidian (external vault storage)
---

## Key Features
1. **Intelligent Task Routing** - Automatic agent selection based on capability and performance score
2. **Hybrid Memory System** - Semantic search (vectors) + explicit storage (Obsidian)
3. **Hebbian Learning** - Agent-task associations strengthen on success, weaken on failure
4. **Modular Agents** - Extensible agent architecture with distinct capabilities
5. **Obsidian Integration** - Read/write tasks directly in Obsidian vault
6. **Comprehensive Logging** - Detailed execution metrics and audit trails
7. **Type Safety** - Full TypeScript/type hints throughout codebase
8. **Web Interface** - Complete React UI for task management and monitoring
9. **Governance Monitoring** - Tracks memory system failures and alerts
---

## Development
### Install Dependencies
**Backend**:

```bash
pip install -r requirements.txt
```
**Frontend**:

```bash
cd web/frontend
npm install
```
### Run Tests
```bash
pytest tests/
```
### Code Quality
```bash
# Frontend linting
cd web/frontend
npm run lint
```
---

## How To Guide
### How To: Execute a Task via CLI
**Basic task execution with automatic agent routing**:

```bash
python main.py -i "Your task description here" -c required_capability
```
**Example: Research task**:

```bash
python main.py -i "Find the latest trends in machine learning" -c web_search
```
**Assign to a specific agent**:

```bash
python main.py --agent artemis_agent -i "Analyze the system architecture" -t "Architecture Analysis"
```
**With custom title**:

```bash
python main.py -i "Summarize this document" -c text_summarization -t "Document Summary"
```
---

### How To: Create and Manage Tasks via Web UI
**Access the web interface**:

1. Start the application: `npm start`
2. Navigate to `http://localhost:3000`
3. Go to **Tasks** page (`/tasks` )
   **Create a new task**:

1. Click "Create New Task" button
2. Fill in task details:
    - **Title**: Brief description
    - **Description**: Detailed task information
    - **Required Capability**: Select from dropdown (web_search, text_summarization, etc.)
    - **Agent** (optional): Leave blank for auto-routing or select specific agent

3. Click "Create Task"
   **Execute a task**:

1. View pending tasks in Tasks page
2. Click on a task to view details
3. Click "Execute" button
4. Monitor execution status in real-time
5. View results when complete
   **Batch execute tasks**:

1. Go to Tasks page
2. Click "Execute All Pending" button
3. View execution progress dashboard
---

### How To: Manage Tasks in Obsidian Vault
**Configure Obsidian integration**:

1. Set up Obsidian vault on your system
2. Create required folders:
    - `Agent Inputs`  - for task notes
    - `Agent Outputs`  - for agent reports

3. Set environment variable:export OBSIDIAN_VAULT_PATH="/path/to/your/vault"
## **Create a task in Obsidian**:
1. Navigate to `Agent Inputs` folder in Obsidian
2. Create new note with YAML frontmatter:
 ```yaml
##  task_id: T001
 required_capability: web_search
 status: pending
 title: "Research AI Trends"
# Research Task
 Find the latest developments in artificial intelligence for 2025.
 Focus on LLM advancements and applications.

```
3. Save the note
4. MCP will automatically discover and process it

**Check task results**:
1. After execution, results appear in `Agent Outputs` folder
2. Review generated report with:
- Execution summary
- Semantic tags
- Structured findings
- Metadata (execution time, tokens used, etc.)

**Monitor task status**:
```bash
python main.py -i "Check all pending tasks" -c system_management --agent artemis_agent
```
---

### How To: View and Analyze Reports
**Via Web UI**:

1. Go to **Reports** page (`/reports` )
2. View list of all generated reports
3. Click on a report to see:
    - Task summary
    - Execution details
    - Agent performance metrics
    - Semantic tags
    - Full task output

**Via CLI**:

```bash
# List all reports
python main.py --show-reports

# View specific report details
python main.py -i "Retrieve report for task T001"
```
**Via Obsidian**:

- Navigate to `Agent Outputs`  folder
- Open report markdown files to review results
---

### How To: Monitor Agent Performance
**View agent statistics**:

```bash
python main.py --agent-stats artemis_agent
```
**Get Hebbian learning network summary**:

```bash
python main.py --show-hebbian
```
**View all registered agents**:

1. Web UI: Go to **Agents** page (`/agents` )
2. CLI:python main.py -i "List all agents" -c system_management --agent artemis_agent
   **Monitor agent scores**:

- Composite score = Alignment (40%) + Accuracy (40%) + Efficiency (20%)
- Scores update automatically after task completion
- Higher scores increase routing probability
---

### How To: Add a New Agent
**Step 1: Create agent file**:

```bash
touch src/agents/my_custom_agent.py
```
**Step 2: Implement agent class**:

```python
from src.agents.base_agent import BaseAgent
from src.types import TaskContext, TaskResult
import logging

logger = logging.getLogger(__name__)

class MyCustomAgent(BaseAgent):
    name = "My Custom Agent"
    capabilities = ["custom_capability", "another_capability"]
    description = "Agent for handling custom tasks"

    def __init__(self):
        super().__init__()
        self.specialty = "custom_capability"

    def perform_task(self, context: TaskContext) -> TaskResult:
        """
        Execute the task with the given context.

        Args:
            context: Task context with instructions and memory

        Returns:
            TaskResult with status, summary, and structured data
        """
        try:
            logger.info(f"Executing task: {context.get('instruction')}")

            # Your task logic here
            result_data = self._process_task(context)

            return {
                "status": "success",
                "summary": f"Successfully processed: {context.get('title')}",
                "data": result_data,
                "semantic_tags": ["processed", "completed"],
                "metrics": {
                    "processing_time": 0.5,
                    "tokens_used": 150
                }
            }
        except Exception as e:
            logger.error(f"Task failed: {str(e)}")
            return {
                "status": "failed",
                "summary": f"Task failed: {str(e)}",
                "error": str(e)
            }

    def _process_task(self, context: TaskContext) -> dict:
        """Internal task processing logic"""
        # Implementation here
        return {"result": "processed"}
```
**Step 3: Register agent in orchestrator**:
Edit `src/mcp/orchestrator.py` and add to `__init__`:

```python
from src.agents.my_custom_agent import MyCustomAgent
self.agents.append(MyCustomAgent())
```
**Step 4: Test the agent**:

```bash
python main.py -i "Test task" -c custom_capability
```
---

### How To: Configure and Deploy
**Environment Setup**:

1. Create `.env`  file in project root:OBSIDIAN_VAULT_PATH=/Users/yourname/Documents/Obsidian
   LOG_LEVEL=INFO
   API_HOST=0.0.0.0
   API_PORT=8000
2. Load environment:source .env
   **Database Management**:

- Databases auto-initialize on first run
- Location: `data/`  directory
- Backup before major updates:cp data/*.db data/backup/
  **Frontend Deployment**:

```bash
cd web/frontend
npm run build
# Output in web/frontend/dist/
```
**Backend Deployment**:

```bash
python -m uvicorn web.api.main:app --host 0.0.0.0 --port 8000
```
---

### How To: Debug and Troubleshoot
**Enable debug logging**:

```bash
export LOG_LEVEL=DEBUG
python main.py -i "Your task" -c capability
```
**Check system health**:

```bash
python main.py --agent artemis_agent -i "Perform system diagnostics"
```
**View execution logs**:

```bash
# Latest execution
tail -f logs/run_*.md

# Search logs for errors
grep -r "error\|failed" logs/
```
**Inspect database contents**:

```bash
# Agent registry
sqlite3 data/agent_registry.db "SELECT * FROM agents LIMIT 5;"

# Hebbian weights
sqlite3 data/hebbian_weights.db "SELECT * FROM node_connections LIMIT 10;"

# Vector store
sqlite3 data/vector_store.db "SELECT doc_id FROM vectors LIMIT 5;"
```
**Reset system state**:

```bash
# Backup first!
mkdir -p data/backup
cp data/*.db data/backup/

# Clear learning data (keeps agent registry)
rm data/hebbian_weights.db data/vector_store.db
```
**Check API health**:

```bash
curl http://localhost:8000/docs  # Swagger UI
curl http://localhost:8000/api/agents  # List agents
```
---

### How To: Integrate with External Systems
**Fetch data from memory bus**:

```python
from src.integration.memory_bus import MemoryBus

memory_bus = MemoryBus()
note_content = memory_bus.read_note("path/to/note.md")
```
**Write results with semantic embedding**:

```python
memory_bus.write_note_with_embedding(
    path="path/to/output.md",
    content="Task results here",
    metadata={"task_id": "T001", "type": "result"}
)
```
**Search semantic memory**:

```python
from src.mcp.vector_store import VectorStore

vector_store = VectorStore()
results = vector_store.search(query_embedding, top_k=5)
for doc in results:
    print(f"Found: {doc['content']}")
```
**Update agent performance**:

```python
from src.integration.agent_registry import AgentRegistry

registry = AgentRegistry()
registry.update_score(
    agent_name="artemis_agent",
    alignment=0.85,
    accuracy=0.92,
    efficiency=0.78
)
```
---

### How To: Optimize Performance
**Optimize vector store queries**:

- Limit `top_k`  parameter for faster results
- Use exact lookup when possible instead of semantic search
- Regular database maintenance:sqlite3 data/vector_store.db "VACUUM;"
  **Improve agent routing**:

- Keep Hebbian weights updated with task results
- Monitor and update agent scores regularly
- Review routing statistics:python main.py --show-hebbian
  **Memory management**:

- Archive old logs: `logs/run_*.md`  files
- Prune vector store of unused embeddings periodically
- Monitor database sizes:du -h data/*.db
---

### How To: Extend Capabilities
**Add new capability to existing agent**:

1. Edit agent file (e.g., `src/agents/research_agent.py` )
2. Add capability to `capabilities`  list:capabilities = ["web_search", "document_analysis", "new_capability"]
3. Implement handling in `perform_task()`  method
4. Update registry routing if needed
   **Create custom task type**:

1. Define task structure in documentation
2. Add task parser if using Obsidian format
3. Update orchestrator routing rules if needed
4. Add corresponding tests
   **Add API endpoint**:

1. Edit `web/api/main.py`
2. Create new route with FastAPI decorator
3. Implement handler logic
4. Document in endpoint docstring
---

### How To: Monitor and Maintain System
**Daily checks**:

- Review governance log: `data/governance_events.log`
- Check error rates in `logs/run_*.md`
- Monitor database sizes in `data/`
  **Weekly maintenance**:

- Archive old logs (older than 7 days)
- Review Hebbian learning network for anomalies
- Update agent performance scores
  **Monthly reviews**:

- Analyze agent effectiveness metrics
- Review task success rates by capability
- Plan for new agent additions if needed
  **Performance benchmarks**:

- Track task execution time trends
- Monitor memory consumption
- Review API response times via Swagger UI
---

## Architecture Diagram
```apache
┌─────────────────────────────────────────────────┐
│          User Interface Layer                   │
│  ┌───────────────────────────────────────────┐  │
│  │ CLI (main.py)  │  Web UI (React)         │  │
│  │ Commands       │  - Dashboard            │  │
│  │ - instruction  │  - Tasks                │  │
│  │ - capability   │  - Reports              │  │
│  │ - agent        │  - Agents               │  │
│  └───────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │   FastAPI Backend        │
        │   (port 8000)            │
        │   /api/agents, /api/tasks│
        └────────────┬─────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │     ORCHESTRATOR         │
        │  (central coordinator)   │
        └────────┬────────┬────────┘
                 │        │
         ┌───────▼─┐  ┌───▼───────┐
         │         │  │           │
     ┌───▼──┐      │  │  ┌────────▼────┐
     │AGENTS│      │  │  │MEMORY LAYER  │
     │      │      │  │  │              │
     │-Artemis│     │  │  │┌─────────┐   │
     │-Research│    │  │  ││Vector   │   │
     │-Summarizer│  │  │  ││Store    │   │
     └───────┘     │  │  │└─────────┘   │
                   │  │  │              │
                   │  │  │┌─────────┐   │
                   │  │  ││Obsidian │   │
                   │  │  ││Integration│  │
                   │  │  │└─────────┘   │
                   │  │  └──────────────┘
                   │  │
           ┌───────▼──▼──────────┐
           │ AGENT REGISTRY      │
           │ (routing, scoring)  │
           └─────────────────────┘

┌─────────────────────────────────────────┐
│    Persistence Layer (SQLite)           │
│                                         │
│  - agent_registry.db (metadata)        │
│  - hebbian_weights.db (learning)       │
│  - vector_store.db (embeddings)        │
│  - run_logs.db (metrics)               │
│  - governance_events.log (failures)    │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│    External: Obsidian Vault             │
│                                         │
│  - Agent Inputs (task notes)            │
│  - Agent Outputs (reports)              │
└─────────────────────────────────────────┘
```
---

## Extending the System
### Adding a New Agent
1. Create new file: `src/agents/my_agent.py`
2. Inherit from `BaseAgent`
3. Implement `perform_task(context)`  method
4. Define `name`  and `capabilities`  class attributes
5. Register in orchestrator initialization
   Example:

```python
from src.agents.base_agent import BaseAgent
from src.types import TaskContext, TaskResult

class MyAgent(BaseAgent):
    name = "My Agent"
    capabilities = ["my_capability"]

    def perform_task(self, context: TaskContext) -> TaskResult:
        # Implementation
        return {
            "status": "success",
            "summary": "Task completed"
        }
```
### Adding a New Capability
1. Update `BaseAgent.capabilities`  list
2. Update `AgentRegistry`  scoring if needed
3. Update task routing logic if needed
---

## Troubleshooting
**Obsidian Vault Not Found**:

- Set `OBSIDIAN_VAULT_PATH`  in `.env`
- Ensure path exists and is readable
  **Agent Not Registered**:

- Check agent name in CLI/API
- Verify agent class is imported in orchestrator
  **Memory Sync Failures**:

- Check `data/governance_events.log`  for error details
- Verify Obsidian vault permissions
- Check vector store database integrity
  **API Connection Issues**:

- Ensure FastAPI backend is running on port 8000
- Check CORS configuration if using different domain
---



