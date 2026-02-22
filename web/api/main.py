import sys
import os
import json
import logging
import sqlite3
from pathlib import Path
from typing import List, Dict, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def _sanitize_for_log(value: Any) -> str:
    """
    Basic sanitization for values that will be written to logs.
    Removes carriage returns and newlines to mitigate log injection.
    """
    text = str(value)
    return text.replace("\r", "").replace("\n", "")

import_error: Exception | None = None

try:
    from src.mcp.orchestrator import Orchestrator
    from src.mcp.config import AGENT_OUTPUT_DIR
    from src.utils.helpers import logger
except Exception as e:
    import_error = e
    Orchestrator = None  # type: ignore[assignment]
    AGENT_OUTPUT_DIR = "Agent Outputs"
    logger = logging.getLogger("mcp_dashboard_api")
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)
    logger.warning("Orchestrator dependencies unavailable. SQLite-only mode enabled: %s", e)


# --- Pydantic Models ---
class TaskData(BaseModel):
    task_id: str | None = Field(default_factory=lambda: f"task_{os.urandom(4).hex()}")
    agent: str
    status: str = "pending"
    title: str = "Untitled Task"
    required_capability: str | None = None
    context: str | None = None
    keywords: str | None = None
    target: str | None = None
    subtasks: List[Dict[str, Any]] | None = None


class AgentResponse(BaseModel):
    name: str
    capabilities: List[str]


class ReportSummary(BaseModel):
    filename: str
    agent: str
    task_id: str
    timestamp: str


class AgentScore(BaseModel):
    name: str
    capabilities: List[str]
    alignment: float
    accuracy: float
    efficiency: float
    composite_score: float


class HebbianConnection(BaseModel):
    origin_node: str
    target_node: str
    weight: float
    activation_count: int
    success_count: int
    failure_count: int
    success_rate: float


class HebbianStats(BaseModel):
    total_connections: int
    avg_weight: float
    max_weight: float
    total_activations: int
    total_successes: int
    success_rate: float


class VectorStoreStats(BaseModel):
    total_docs: int
    avg_content_length: float


class RunSummary(BaseModel):
    run_id: str
    start_time: str
    end_time: str
    total_events: int


class ExecuteInstructionRequest(BaseModel):
    instruction: str
    capability: str | None = None
    agent: str | None = None
    title: str | None = None


class ExecuteInstructionResponse(BaseModel):
    task_id: str
    status: str
    summary: str
    note_path: str | None = None
    error: str | None = None


DB_DIR = Path(__file__).resolve().parent / "db"
AGENT_REGISTRY_DB = DB_DIR / "agent_registry.db"
HEBBIAN_DB = DB_DIR / "hebbian_weights.db"
VECTOR_DB = DB_DIR / "vector_store.db"
RUN_LOG_DB = DB_DIR / "run_logs.db"


def _connect_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        raise HTTPException(status_code=500, detail="Database unavailable.")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _parse_json(text: Any, fallback: Any):
    if text is None:
        return fallback
    if isinstance(text, (dict, list)):
        return text
    if not isinstance(text, str):
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return fallback


def _safe_rate(successes: int, total: int) -> float:
    return (successes / total) if total else 0.0


# --- FastAPI App Setup ---
app = FastAPI(
    title="MCP Obsidian API",
    description="API for managing tasks and agents with Obsidian integration.",
    version="0.1.0",
)

# Add CORS middleware
_cors_origins_raw = os.environ.get("FASTAPI_CORS_ORIGINS", "http://localhost:3000,http://localhost:4000")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# --- API Key Authentication ---
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_FASTAPI_API_KEY = os.environ.get("FASTAPI_API_KEY") or os.environ.get("MCP_API_KEY")


async def _require_api_key(api_key: str | None = Depends(_api_key_header)):
    """Validate the API key from the X-API-Key header."""
    if not _FASTAPI_API_KEY:
        # No key configured — allow requests (local dev without .env)
        return
    if not api_key or api_key != _FASTAPI_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


# --- Orchestrator Instance ---
try:
    if Orchestrator is None:
        orchestrator = None
    else:
        orchestrator = Orchestrator()
        logger.info("Orchestrator initialized for FastAPI.")
except Exception as e:
    logger.error("Failed to initialize Orchestrator: %s", _sanitize_for_log(e))
    # Depending on the severity, you might want to exit or provide a fallback
    orchestrator = None  # type: ignore


@app.on_event("startup")
async def startup_event():
    if import_error:
        logger.warning("Startup in SQLite-only mode due to import error: %s", import_error)
    if orchestrator:
        logger.info("FastAPI application starting up. Orchestrator ready.")
    else:
        logger.error(
            "FastAPI application starting up, but Orchestrator failed to initialize."
        )


# --- API Endpoints ---


@app.get("/api/agents", response_model=List[AgentResponse])
async def get_agents(_key: None = Depends(_require_api_key)):
    """Lists all registered agents."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    return [
        AgentResponse(name=agent.name, capabilities=getattr(agent, "capabilities", []))
        for agent in orchestrator.agent_registry.get_all_agents()
    ]


@app.get("/api/tasks")
async def get_tasks(_key: None = Depends(_require_api_key)):
    """Retrieves all pending tasks from Obsidian."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    try:
        tasks_with_paths = orchestrator.check_for_new_tasks_from_obsidian()
        formatted_tasks = []
        for path, data in tasks_with_paths:
            if "task_id" not in data:
                data["task_id"] = f"task_{hash(path) % 100000}"
            formatted_tasks.append({**data, "relative_path": path})
        return formatted_tasks
    except Exception as e:
        logger.error("Error fetching tasks: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch tasks.")


@app.post("/api/tasks", status_code=201)
async def create_task(task_data: TaskData, _key: None = Depends(_require_api_key)):
    """Creates a new task in Obsidian for an agent."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    try:
        payload = task_data.model_dump()
        relative_path = orchestrator.create_new_task_in_obsidian(payload)
        resolved_capability = orchestrator._resolve_required_capability(payload)  # type: ignore
        return {
            "message": "Task created successfully",
            "path": relative_path,
            "task_id": task_data.task_id,
            "required_capability": resolved_capability,
        }
    except Exception as e:
        logger.error("Error creating task: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to create task.")


@app.get("/api/reports", response_model=List[ReportSummary])
async def get_reports(_key: None = Depends(_require_api_key)):
    """Lists all generated reports."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    try:
        report_files = orchestrator.obs_manager.list_notes_in_folder(AGENT_OUTPUT_DIR)
        summaries = []
        for filename in report_files:
            parts = filename.replace(".md", "").split("_Report_")
            if len(parts) == 2:
                agent_name = parts[0]
                task_id_and_len = parts[1].rsplit("_", 1)
                task_id = task_id_and_len[0] if len(task_id_and_len) > 1 else "unknown"
            else:
                agent_name = "unknown_agent"
                task_id = "unknown_task"

            summaries.append(
                ReportSummary(
                    filename=filename,
                    agent=agent_name,
                    task_id=task_id,
                    timestamp="N/A",
                )
            )
        return summaries
    except Exception as e:
        logger.error("Error listing reports: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to list reports.")


@app.get("/api/reports/{filename:path}")
async def get_report_content(filename: str, _key: None = Depends(_require_api_key)):
    """Retrieves the content of a specific report."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    try:
        relative_path = os.path.join(AGENT_OUTPUT_DIR, filename)
        content = orchestrator.obs_manager.read_note(relative_path)
        if content is None:
            raise HTTPException(status_code=404, detail="Report not found.")
        return {"filename": filename, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error reading report %s: %s", _sanitize_for_log(filename), _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to read report.")


@app.post("/api/execute-task")
async def execute_pending_task(task_path: Dict[str, str], _key: None = Depends(_require_api_key)):
    """
    Executes a specific pending task identified by its relative_path in Obsidian.
    """
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")

    relative_note_path = task_path.get("relative_path")
    if not relative_note_path:
        raise HTTPException(
            status_code=400, detail="Missing 'relative_path' in request body."
        )

    try:
        content = orchestrator.obs_manager.read_note(relative_note_path)
        if not content:
            raise HTTPException(status_code=404, detail="Task note not found.")

        task_data = orchestrator.obs_parser.parse_task_note(content)
        if not task_data or task_data.get("status", "pending").lower() != "pending":
            raise HTTPException(
                status_code=400, detail="Task is not pending or could not be parsed."
            )

        resolved_capability = orchestrator._resolve_required_capability(task_data)  # type: ignore
        if resolved_capability:
            task_data["required_capability"] = resolved_capability
        else:
            orchestrator.update_task_status_in_obsidian(
                relative_note_path, "no_capability", task_data.get("task_id")
            )
            raise HTTPException(
                status_code=400,
                detail="Task is missing 'required_capability' and none could be inferred.",
            )

        agent_name = task_data.get("agent")
        agent_obj = (
            orchestrator.agent_registry.get_agent(agent_name) if agent_name else None
        )

        orchestrator.update_task_status_in_obsidian(
            relative_note_path, "in progress", task_data.get("task_id")
        )

        if agent_obj:
            results = orchestrator.assign_and_execute_task(
                agent_obj.name, task_data, relative_note_path
            )
        else:
            logger.warning(
                "No registered agent for %s. Routing by capability %s.",
                _sanitize_for_log(agent_name),
                _sanitize_for_log(resolved_capability),
            )
            results = orchestrator.route_and_execute_task(task_data, relative_note_path)

        return {"message": "Task executed successfully", "results": results}
    except ValueError as ve:
        logger.error("Validation error executing task: %s", _sanitize_for_log(ve))
        orchestrator.update_task_status_in_obsidian(relative_note_path, "failed", task_data.get("task_id"))  # type: ignore
        raise HTTPException(status_code=400, detail="Invalid task data.")
    except HTTPException:
        raise
    except Exception as e:
        if "task_data" in locals() and "relative_note_path" in locals():
            orchestrator.update_task_status_in_obsidian(relative_note_path, "failed", task_data.get("task_id"))  # type: ignore
        logger.error(
            "Error executing task from %s: %s",
            _sanitize_for_log(relative_note_path),
            _sanitize_for_log(e),
        )
        raise HTTPException(status_code=500, detail="Failed to execute task.")


@app.post("/api/execute-all-pending")
async def execute_all_pending_tasks(_key: None = Depends(_require_api_key)):
    """Executes all pending tasks discovered in the Obsidian input directory."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")

    try:
        summary = orchestrator.execute_all_pending_tasks()
        return summary
    except Exception as e:
        logger.error("Error executing all pending tasks: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to execute pending tasks.")


# --- Database Viewer Endpoints ---


@app.get("/api/db/agents", response_model=List[AgentScore])
async def get_agent_scores(_key: None = Depends(_require_api_key)):
    """Get all agents with their capabilities and performance scores."""
    conn = _connect_db(AGENT_REGISTRY_DB)
    try:
        rows = conn.execute(
            """
            SELECT
              name,
              capabilities,
              COALESCE(alignment, 0.0) AS alignment,
              COALESCE(accuracy, 0.0) AS accuracy,
              COALESCE(efficiency, 0.0) AS efficiency
            FROM agents
            ORDER BY name ASC
            """
        ).fetchall()

        agents: List[AgentScore] = []
        for row in rows:
            capabilities = _parse_json(row["capabilities"], [])
            if not isinstance(capabilities, list):
                capabilities = []
            alignment = float(row["alignment"])
            accuracy = float(row["accuracy"])
            efficiency = float(row["efficiency"])
            composite = (alignment + accuracy + efficiency) / 3.0
            agents.append(
                AgentScore(
                    name=row["name"],
                    capabilities=capabilities,
                    alignment=alignment,
                    accuracy=accuracy,
                    efficiency=efficiency,
                    composite_score=composite,
                )
            )
        return agents
    except Exception as e:
        logger.error("Error fetching agent scores: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch agent scores.")
    finally:
        conn.close()


@app.get("/api/db/hebbian/stats", response_model=HebbianStats)
async def get_hebbian_stats(_key: None = Depends(_require_api_key)):
    """Get overall Hebbian network statistics."""
    conn = _connect_db(HEBBIAN_DB)
    try:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS total_connections,
              COALESCE(AVG(weight), 0.0) AS avg_weight,
              COALESCE(MAX(weight), 0.0) AS max_weight,
              COALESCE(SUM(activation_count), 0) AS total_activations,
              COALESCE(SUM(success_count), 0) AS total_successes
            FROM node_connections
            """
        ).fetchone()
        if row is None:
            row = {
                "total_connections": 0,
                "avg_weight": 0.0,
                "max_weight": 0.0,
                "total_activations": 0,
                "total_successes": 0,
            }
        total_activations = int(row["total_activations"])
        total_successes = int(row["total_successes"])
        return HebbianStats(
            total_connections=int(row["total_connections"]),
            avg_weight=float(row["avg_weight"]),
            max_weight=float(row["max_weight"]),
            total_activations=total_activations,
            total_successes=total_successes,
            success_rate=_safe_rate(total_successes, total_activations),
        )
    except Exception as e:
        logger.error("Error fetching Hebbian stats: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch Hebbian stats.")
    finally:
        conn.close()


@app.get("/api/db/hebbian/connections", response_model=List[HebbianConnection])
async def get_hebbian_connections(limit: int = 50, _key: None = Depends(_require_api_key)):
    """Get top Hebbian connections by weight."""
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    conn = _connect_db(HEBBIAN_DB)
    try:
        rows = conn.execute(
            """
            SELECT
              origin_node,
              target_node,
              COALESCE(weight, 0.0) AS weight,
              COALESCE(activation_count, 0) AS activation_count,
              COALESCE(success_count, 0) AS success_count,
              COALESCE(failure_count, 0) AS failure_count
            FROM node_connections
            ORDER BY weight DESC, activation_count DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            HebbianConnection(
                origin_node=row["origin_node"] or "",
                target_node=row["target_node"] or "",
                weight=float(row["weight"]),
                activation_count=int(row["activation_count"]),
                success_count=int(row["success_count"]),
                failure_count=int(row["failure_count"]),
                success_rate=_safe_rate(int(row["success_count"]), int(row["activation_count"])),
            )
            for row in rows
        ]
    except Exception as e:
        logger.error("Error fetching Hebbian connections: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch Hebbian connections.")
    finally:
        conn.close()


@app.get("/api/db/hebbian/agent/{agent_name}")
async def get_agent_hebbian_stats(agent_name: str, _key: None = Depends(_require_api_key)):
    """Get Hebbian statistics for a specific agent."""
    conn = _connect_db(HEBBIAN_DB)
    try:
        stats_row = conn.execute(
            """
            SELECT
              COALESCE(AVG(weight), 0.0) AS avg_weight,
              COALESCE(SUM(activation_count), 0) AS total_activations,
              COALESCE(SUM(success_count), 0) AS total_successes
            FROM node_connections
            WHERE origin_node = ?
            """,
            (agent_name,),
        ).fetchone()
        top_rows = conn.execute(
            """
            SELECT target_node, COALESCE(weight, 0.0) AS weight
            FROM node_connections
            WHERE origin_node = ?
            ORDER BY weight DESC
            LIMIT 10
            """,
            (agent_name,),
        ).fetchall()

        if stats_row is None:
            avg_weight = 0.0
            total_activations = 0
            total_successes = 0
        else:
            avg_weight = float(stats_row["avg_weight"])
            total_activations = int(stats_row["total_activations"])
            total_successes = int(stats_row["total_successes"])

        return {
            "agent_name": agent_name,
            "average_weight": avg_weight,
            "success_rate": _safe_rate(total_successes, total_activations),
            "strongest_connections": [
                {"target": row["target_node"], "weight": float(row["weight"])} for row in top_rows
            ],
        }
    except Exception as e:
        logger.error("Error fetching agent Hebbian stats: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch agent Hebbian stats.")
    finally:
        conn.close()


@app.get("/api/db/vectors/stats", response_model=VectorStoreStats)
async def get_vector_stats(_key: None = Depends(_require_api_key)):
    """Get vector store statistics."""
    conn = _connect_db(VECTOR_DB)
    try:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS total_docs,
              COALESCE(AVG(LENGTH(COALESCE(content, ''))), 0.0) AS avg_content_length
            FROM vectors
            """
        ).fetchone()
        if row is None:
            return VectorStoreStats(total_docs=0, avg_content_length=0.0)
        return VectorStoreStats(
            total_docs=int(row["total_docs"]),
            avg_content_length=float(row["avg_content_length"]),
        )
    except Exception as e:
        logger.error("Error fetching vector stats: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch vector stats.")
    finally:
        conn.close()


@app.get("/api/db/vectors/list")
async def list_vectors(limit: int = 100, offset: int = 0, _key: None = Depends(_require_api_key)):
    """List vectors in the store with pagination."""
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    conn = _connect_db(VECTOR_DB)
    try:
        rows = conn.execute(
            """
            SELECT doc_id, metadata, content
            FROM vectors
            ORDER BY doc_id
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        vectors = []
        for row in rows:
            metadata = _parse_json(row["metadata"], {})
            if not isinstance(metadata, dict):
                metadata = {"raw": row["metadata"]}
            vectors.append(
                {
                    "doc_id": row["doc_id"],
                    "metadata": metadata,
                    "content": row["content"] or "",
                }
            )
        return vectors
    except Exception as e:
        logger.error("Error listing vectors: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to list vectors.")
    finally:
        conn.close()


@app.get("/api/db/runs", response_model=List[RunSummary])
async def get_runs(limit: int = 20, _key: None = Depends(_require_api_key)):
    """Get recent runs with summary statistics."""
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    conn = _connect_db(RUN_LOG_DB)
    try:
        rows = conn.execute(
            """
            SELECT
              run_id,
              MIN(timestamp) AS start_time,
              MAX(timestamp) AS end_time,
              COUNT(*) AS total_events,
              MAX(created_at) AS latest_created_at
            FROM event_log
            GROUP BY run_id
            ORDER BY latest_created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            RunSummary(
                run_id=row["run_id"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                total_events=int(row["total_events"]),
            )
            for row in rows
        ]
    except Exception as e:
        logger.error("Error fetching runs: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch runs.")
    finally:
        conn.close()


@app.get("/api/db/runs/{run_id}/events")
async def get_run_events_endpoint(run_id: str, event_type: str | None = None, _key: None = Depends(_require_api_key)):
    """Get events for a specific run."""
    conn = _connect_db(RUN_LOG_DB)
    try:
        query = """
            SELECT
              timestamp,
              event_type,
              component,
              message,
              metadata,
              duration_ms
            FROM event_log
            WHERE run_id = ?
        """
        params: List[Any] = [run_id]
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY created_at ASC, id ASC"

        rows = conn.execute(query, tuple(params)).fetchall()
        events = []
        for row in rows:
            events.append(
                {
                    "timestamp": row["timestamp"],
                    "event_type": row["event_type"],
                    "component": row["component"],
                    "message": row["message"],
                    "metadata": _parse_json(row["metadata"], {}),
                    "duration_ms": row["duration_ms"],
                }
            )
        return events
    except Exception as e:
        logger.error("Error fetching run events: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch run events.")
    finally:
        conn.close()


# --- CLI Executor Endpoint ---


@app.post("/api/cli/execute", response_model=ExecuteInstructionResponse)
async def execute_instruction(request: ExecuteInstructionRequest, _key: None = Depends(_require_api_key)):
    """
    Execute a CLI-style instruction with optional agent/capability specification.
    Mimics the behavior of: python main.py -i "instruction" -c "capability" --agent "agent_name"
    """
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")

    if not request.instruction.strip():
        raise HTTPException(status_code=400, detail="Instruction cannot be empty.")

    try:
        from datetime import datetime
        import time

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        task_id = f"user_instruction_{timestamp}"
        task_title = request.title or request.instruction.strip().split("\n")[0][:80]

        # Resolve capability and agent
        effective_capability = request.capability or "web_search"
        agent_for_dispatch = None

        if request.agent:
            agent_for_dispatch = orchestrator.agent_registry.get_agent(request.agent)
            if not agent_for_dispatch:
                raise HTTPException(
                    status_code=400,
                    detail="Specified agent not found.",
                )
            if not request.capability and agent_for_dispatch.capabilities:
                effective_capability = agent_for_dispatch.capabilities[0]

        # Build task data
        task_data = {
            "task_id": task_id,
            "title": task_title,
            "context": request.instruction,
            "content": request.instruction,
            "required_capability": effective_capability,
            "status": "pending",
            "tags": ["user_instruction", effective_capability],
        }

        if agent_for_dispatch:
            task_data["agent"] = agent_for_dispatch.name

        # Create task in Obsidian
        note_path = None
        try:
            note_path = orchestrator.create_new_task_in_obsidian(task_data)
            orchestrator.update_task_status_in_obsidian(note_path, "in progress", task_id)
        except Exception as e:
            logger.error("Failed to create task in Obsidian: %s", _sanitize_for_log(e))

        # Execute task
        try:
            if agent_for_dispatch:
                result = orchestrator.assign_and_execute_task(
                    agent_for_dispatch.name, task_data, note_path
                )
            else:
                result = orchestrator.route_and_execute_task(task_data, note_path)

            return ExecuteInstructionResponse(
                task_id=task_id,
                status="success",
                summary=result.get("summary", "Task executed"),
                note_path=note_path,
                error=None,
            )
        except Exception as e:
            logger.error("Error executing instruction: %s", _sanitize_for_log(e))
            if note_path:
                orchestrator.update_task_status_in_obsidian(note_path, "failed", task_id)
            return ExecuteInstructionResponse(
                task_id=task_id,
                status="failed",
                summary="Task execution failed",
                note_path=note_path,
                error=None,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error processing instruction: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to process instruction.")
