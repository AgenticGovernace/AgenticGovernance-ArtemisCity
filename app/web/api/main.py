import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.mcp.orchestrator import Orchestrator
from src.mcp.config import AGENT_OUTPUT_DIR
from src.utils.helpers import logger


# --- Pydantic Models ---
class TaskData(BaseModel):
    task_id: str | None = Field(default_factory=lambda: f"task_{os.urandom(4).hex()}")
    agent: str
    status: str = "pending"
    title: str = "Untitled Task"
    context: str | None = None
    keywords: str | None = None
    target: str | None = None
    subtasks: List[Dict[str, Any]] | None = None


class AgentResponse(BaseModel):
    name: str


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for development. Restrict in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Orchestrator Instance ---
try:
    orchestrator = Orchestrator()
    logger.info("Orchestrator initialized for FastAPI.")
except Exception as e:
    logger.error(f"Failed to initialize Orchestrator: {e}")
    # Depending on the severity, you might want to exit or provide a fallback
    orchestrator = None  # type: ignore


@app.on_event("startup")
async def startup_event():
    if orchestrator:
        logger.info("FastAPI application starting up. Orchestrator ready.")
    else:
        logger.error("FastAPI application starting up, but Orchestrator failed to initialize.")


# --- API Endpoints ---

@app.get("/api/agents", response_model=List[AgentResponse])
async def get_agents():
    """Lists all registered agents."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    return [{"name": name} for name in orchestrator.agents.keys()]


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
            if 'task_id' not in data:
                data['task_id'] = f"task_{hash(path) % 100000}"
            formatted_tasks.append({**data, "relative_path": path})
        return formatted_tasks
    except Exception as e:
        logger.error(f"Error fetching tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching tasks: {e}")


@app.post("/api/tasks", status_code=201)
async def create_task(task_data: TaskData):
    """Creates a new task in Obsidian for an agent."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    try:
        # Use the Orchestrator's method to create the note
        relative_path = orchestrator.create_new_task_in_obsidian(task_data.model_dump())
        return {"message": "Task created successfully", "path": relative_path,
                "task_id": task_data.task_id}
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating task: {e}")


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
            parts = filename.replace('.md', '').split('_Report_')
            if len(parts) == 2:
                agent_name = parts[0]
                task_id_and_len = parts[1].rsplit('_', 1)
                task_id = task_id_and_len[0] if len(task_id_and_len) > 1 else "unknown"
            else:
                agent_name = "unknown_agent"
                task_id = "unknown_task"

            summaries.append(ReportSummary(
                filename=filename,
                agent=agent_name,
                task_id=task_id,
                timestamp="N/A"  # Could parse from file content if needed
            ))
        return summaries
    except Exception as e:
        logger.error(f"Error listing reports: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing reports: {e}")


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
        logger.error(f"Error reading report {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading report: {e}")


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
        raise HTTPException(status_code=400, detail="Missing 'relative_path' in request body.")

    try:
        content = orchestrator.obs_manager.read_note(relative_note_path)
        if not content:
            raise HTTPException(status_code=404,
                                detail=f"Task note not found at {relative_note_path}")

        task_data = orchestrator.obs_parser.parse_task_note(content)
        if not task_data or task_data.get('status', 'pending').lower() != 'pending':
            raise HTTPException(status_code=400,
                                detail="Task is not pending or could not be parsed.")

        agent_name = task_data.get('agent')
        if not agent_name or agent_name not in orchestrator.agents:
            orchestrator.update_task_status_in_obsidian(relative_note_path, 'agent_not_found',
                                                        task_data.get('task_id'))
            raise HTTPException(status_code=400,
                                detail=f"Agent '{agent_name}' not found or not registered.")

        # Update status to in progress
        orchestrator.update_task_status_in_obsidian(relative_note_path, 'in progress',
                                                    task_data.get('task_id'))

        # Execute the task
        results = orchestrator.assign_and_execute_task(agent_name, task_data, relative_note_path)

        return {"message": "Task executed successfully", "results": results}
    except ValueError as ve:
        orchestrator.update_task_status_in_obsidian(relative_note_path, 'failed',
                                                    task_data.get('task_id'))  # type: ignore
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise  # Re-raise FastAPI HTTPExceptions
    except Exception as e:
        # If task_data and relative_note_path are available, update status to failed
        if 'task_data' in locals() and 'relative_note_path' in locals():
            orchestrator.update_task_status_in_obsidian(relative_note_path, 'failed',
                                                        task_data.get('task_id'))  # type: ignore
        logger.error(f"Error executing task from {relative_note_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Error executing task: {e}")
