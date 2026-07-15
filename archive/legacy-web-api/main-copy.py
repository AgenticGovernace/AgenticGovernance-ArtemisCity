import os
import re
import sys
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.mcp.config import AGENT_OUTPUT_DIR
from src.mcp.orchestrator import Orchestrator
from src.utils.helpers import logger

_LOG_CONTROL_CHARS = re.compile(r"[\r\n\x00-\x1f\x7f]+")


def _sanitize_for_log(value: Any) -> str:
    return _LOG_CONTROL_CHARS.sub(" ", str(value))


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


# --- FastAPI App Setup ---
app = FastAPI(
    title="MCP Obsidian API",
    description="API for managing tasks and agents with Obsidian integration.",
    version="0.1.0",
)

# Add CORS middleware
_cors_origins_raw = os.environ.get("FASTAPI_CORS_ORIGINS", "")
_cors_origins = [
    o.strip() for o in _cors_origins_raw.split(",") if o.strip() and o.strip() != "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# --- Orchestrator Instance ---
try:
    orchestrator = Orchestrator
    logger.info("Orchestrator initialized for FastAPI.")
except Exception as e:
    logger.error("Failed to initialize Orchestrator: %s", _sanitize_for_log(e))
    # Depending on the severity, you might want to exit or provide a fallback
    orchestrator = None  # type: ignore


@app.on_event("startup")
async def startup_event():
    if orchestrator:
        logger.info("FastAPI application starting up. Orchestrator ready.")
    else:
        logger.error(
            "FastAPI application starting up, but Orchestrator failed to initialize."
        )


# --- API Endpoints ---


@app.get("/api/agents", response_model=List[AgentResponse])
async def get_agents():
    """Lists all registered agents."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    return [
        AgentResponse(name=agent.name, capabilities=getattr(agent, "capabilities", []))
        for agent in orchestrator.agent_registry.get_all_agents()
    ]


@app.get("/api/tasks")
async def get_tasks():
    """Retrieves all pending tasks from Obsidian."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    try:
        # check_for_new_tasks_from_obsidian returns list of (relative_path, parsed_task_data)
        tasks_with_paths = orchestrator.check_for_new_tasks_from_obsidian()
        # For the API, we might want to return the parsed_task_data directly,
        # possibly with the path included as a field.
        # Note: This will only return *pending* tasks. We might want to extend this
        # to return all tasks, or tasks by status, in the future.
        formatted_tasks = []
        for path, data in tasks_with_paths:
            # Ensure task_id is always present
            if "task_id" not in data:
                data["task_id"] = f"task_{hash(path) % 100000}"
            formatted_tasks.append({**data, "relative_path": path})
        return formatted_tasks
    except Exception as e:
        logger.error("Error fetching tasks: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch tasks.")


@app.post("/api/tasks", status_code=201)
async def create_task(task_data: TaskData):
    """Creates a new task in Obsidian for an agent."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    try:
        # Use the Orchestrator's method to create the note
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
async def get_reports():
    """Lists all generated reports."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    try:
        report_files = orchestrator.obs_manager.list_notes_in_folder(AGENT_OUTPUT_DIR)
        summaries = []
        for filename in report_files:
            # Attempt to parse filename to extract agent and task_id
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
                    timestamp="N/A",  # Could parse from file content if needed
                )
            )
        return summaries
    except Exception as e:
        logger.error("Error listing reports: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to list reports.")


@app.get("/api/reports/{filename:path}")
async def get_report_content(filename: str):
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
        raise HTTPException(status_code=404, detail="Report file not found.")
    except Exception as e:
        logger.error(
            "Error reading report %s: %s",
            _sanitize_for_log(filename),
            _sanitize_for_log(e),
        )
        raise HTTPException(status_code=500, detail="Failed to read report.")


@app.post("/api/execute-task")
async def execute_pending_task(task_path: Dict[str, str]):
    """
    Executes a specific pending task identified by its relative_path in Obsidian.
    This endpoint is designed to mimic the manual execution from the main.py loop
    for a single task found in Obsidian.
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
                detail="Task is missing 'required_capability' and none could be inferred from the agent.",
            )

        agent_name = task_data.get("agent")
        agent_obj = (
            orchestrator.agent_registry.get_agent(agent_name) if agent_name else None
        )

        # Update status to in progress
        orchestrator.update_task_status_in_obsidian(
            relative_note_path, "in progress", task_data.get("task_id")
        )

        # Execute the task with a preference for the specified agent; fall back to routing by capability.
        if agent_obj:
            results = orchestrator.assign_and_execute_task(
                agent_obj.name, task_data, relative_note_path
            )
        else:
            logger.warning(
                "No registered agent found for '%s'. Routing by capability '%s'.",
                _sanitize_for_log(agent_name),
                _sanitize_for_log(resolved_capability),
            )
            results = orchestrator.route_and_execute_task(task_data, relative_note_path)

        return {"message": "Task executed successfully", "results": results}
    except ValueError as ve:
        orchestrator.update_task_status_in_obsidian(
            relative_note_path, "failed", task_data.get("task_id")
        )  # type: ignore
        logger.error("Task validation error: %s", _sanitize_for_log(ve))
        raise HTTPException(status_code=400, detail="Invalid task payload.")
    except HTTPException:
        raise  # Re-raise FastAPI HTTPExceptions
    except Exception as e:
        # If task_data and relative_note_path are available, update status to failed
        if "task_data" in locals() and "relative_note_path" in locals():
            orchestrator.update_task_status_in_obsidian(
                relative_note_path, "failed", task_data.get("task_id")
            )  # type: ignore
        logger.error(
            "Error executing task from %s: %s",
            _sanitize_for_log(relative_note_path),
            _sanitize_for_log(e),
        )
        raise HTTPException(status_code=500, detail="Failed to execute task.")


@app.post("/api/execute-all-pending")
async def execute_all_pending_tasks():
    """Executes all pending tasks discovered in the Obsidian input directory."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")

    try:
        summary = orchestrator.execute_all_pending_tasks()
        return summary
    except Exception as e:
        logger.error("Error executing all pending tasks: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to execute pending tasks.")
