import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

# Add the project root to the Python path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.obsidian_integration.parser import ObsidianParser  # noqa: E402
from src.runtime_paths import data_dir, data_path  # noqa: E402

_shared_sanitize_for_log: Callable[..., str] | None
try:
    from src.utils import helpers as _shared_helpers
except Exception:  # pragma: no cover - SQLite-only fallback mode
    _shared_sanitize_for_log = None
else:
    _shared_sanitize_for_log = _shared_helpers.sanitize_for_log


def _sanitize_for_log(value: Any) -> str:
    """
    Basic sanitization for values that will be written to logs.
    Delegates to the shared ``src.utils.helpers.sanitize_for_log`` when
    the Python core is importable; otherwise falls back to stripping
    carriage returns and newlines to mitigate log injection.
    """
    if _shared_sanitize_for_log is not None:
        return _shared_sanitize_for_log(value)
    text = str(value)
    return text.replace("\r", "").replace("\n", "")


import_error: Exception | None = None

try:
    from src.mcp.config import (AGENT_INPUT_DIR, AGENT_OUTPUT_DIR,
                                OBSIDIAN_VAULT_PATH)
    from src.mcp.orchestrator import Orchestrator
    from src.utils.helpers import logger
except Exception as e:
    import_error = e
    Orchestrator = None  # type: ignore
    AGENT_OUTPUT_DIR = "Agent Outputs"
    AGENT_INPUT_DIR = "Agent Inputs"
    OBSIDIAN_VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "")
    logger = logging.getLogger("mcp_dashboard_api")
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)
    logger.warning(
        "Orchestrator dependencies unavailable. SQLite-only mode enabled: %s", e
    )


# --- Pydantic Models ---
class TaskData(BaseModel):
    """Represent the payload used to create or execute a task through the FastAPI service.

    Attributes:
        task_id (str | None): Stored value on the TaskData instance.
        agent (str): Stored value on the TaskData instance.
        status (str): Stored value on the TaskData instance.
        title (str): Stored value on the TaskData instance.
        required_capability (str | None): Stored value on the TaskData instance.
        context (str | None): Stored value on the TaskData instance.
        keywords (str | None): Stored value on the TaskData instance.
        target (str | None): Stored value on the TaskData instance.
        subtasks (List[Dict[str, Any]] | None): Stored value on the TaskData instance.
    """

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
    """Represent the API response for a registered agent listing entry.

    Attributes:
        name (str): Stored value on the AgentResponse instance.
        capabilities (List[str]): Stored value on the AgentResponse instance.
    """

    name: str
    capabilities: List[str]


class ReportSummary(BaseModel):
    """Represent summarized metadata for a generated report.

    Attributes:
        filename (str): Stored value on the ReportSummary instance.
        agent (str): Stored value on the ReportSummary instance.
        task_id (str): Stored value on the ReportSummary instance.
        timestamp (str): Stored value on the ReportSummary instance.
    """

    filename: str
    agent: str
    task_id: str
    timestamp: str


class AgentScore(BaseModel):
    """Represent persisted scoring details for an agent record.

    Attributes:
        name (str): Stored value on the AgentScore instance.
        capabilities (List[str]): Stored value on the AgentScore instance.
        alignment (float): Stored value on the AgentScore instance.
        accuracy (float): Stored value on the AgentScore instance.
        efficiency (float): Stored value on the AgentScore instance.
        composite_score (float): Stored value on the AgentScore instance.
    """

    name: str
    capabilities: List[str]
    alignment: float
    accuracy: float
    efficiency: float
    composite_score: float
    trust_tier: str = "monitored"
    status: str = "active"
    violation_count: int = 0
    trust_score: float | None = None
    execution_count: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    hebbian_weight: float | None = None
    hebbian_delta: float = 0.0
    hebbian_activations: int = 0
    hebbian_success_rate: float = 0.0
    hebbian_task_type: str | None = None
    hebbian_pair_bonus: float = 0.0
    hebbian_timing_score: float | None = None
    routing_intelligence: float = 0.0
    hebbian_oscillation_rate: float = 0.0
    hebbian_sentinel_alert: bool = False
    hebbian_sentinel_samples: int = 0
    learning_updated_at: str | None = None


class HebbianConnection(BaseModel):
    """Represent a Hebbian edge returned by the database inspection endpoints.

    Attributes:
        origin_node (str): Stored value on the HebbianConnection instance.
        target_node (str): Stored value on the HebbianConnection instance.
        weight (float): Stored value on the HebbianConnection instance.
        activation_count (int): Stored value on the HebbianConnection instance.
        success_count (int): Stored value on the HebbianConnection instance.
        failure_count (int): Stored value on the HebbianConnection instance.
        success_rate (float): Stored value on the HebbianConnection instance.
    """

    origin_node: str
    target_node: str
    weight: float
    activation_count: int
    success_count: int
    failure_count: int
    success_rate: float


class HebbianStats(BaseModel):
    """Represent aggregate Hebbian network statistics returned by the API.

    Attributes:
        total_connections (int): Stored value on the HebbianStats instance.
        avg_weight (float): Stored value on the HebbianStats instance.
        max_weight (float): Stored value on the HebbianStats instance.
        total_activations (int): Stored value on the HebbianStats instance.
        total_successes (int): Stored value on the HebbianStats instance.
        success_rate (float): Stored value on the HebbianStats instance.
    """

    total_connections: int
    avg_weight: float
    max_weight: float
    total_activations: int
    total_successes: int
    success_rate: float


class VectorStoreStats(BaseModel):
    """Represent aggregate statistics for the local vector store.

    Attributes:
        total_docs (int): Stored value on the VectorStoreStats instance.
        avg_content_length (float): Stored value on the VectorStoreStats instance.
    """

    total_docs: int
    avg_content_length: float


class RunSummary(BaseModel):
    """Represent summary metadata for a recorded orchestration run.

    Attributes:
        run_id (str): Stored value on the RunSummary instance.
        start_time (str): Stored value on the RunSummary instance.
        end_time (str): Stored value on the RunSummary instance.
        total_events (int): Stored value on the RunSummary instance.
    """

    run_id: str
    start_time: str
    end_time: str
    total_events: int


class ExecuteInstructionRequest(BaseModel):
    """Represent the request body used to execute a CLI-style instruction.

    Attributes:
        instruction (str): Stored value on the ExecuteInstructionRequest instance.
        capability (str | None): Stored value on the ExecuteInstructionRequest instance.
        agent (str | None): Stored value on the ExecuteInstructionRequest instance.
        title (str | None): Stored value on the ExecuteInstructionRequest instance.
    """

    instruction: str
    capability: str | None = None
    agent: str | None = None
    title: str | None = None
    atp_strict: bool = False


class ExecuteInstructionResponse(BaseModel):
    """Represent the response returned after executing a CLI-style instruction.

    Attributes:
        task_id (str): Stored value on the ExecuteInstructionResponse instance.
        status (str): Stored value on the ExecuteInstructionResponse instance.
        summary (str): Stored value on the ExecuteInstructionResponse instance.
        note_path (str | None): Stored value on the ExecuteInstructionResponse instance.
        error (str | None): Stored value on the ExecuteInstructionResponse instance.
    """

    task_id: str
    status: str
    summary: str
    note_path: str | None = None
    error: str | None = None
    # Which agent actually executed the task. For agent-explicit calls this
    # is request.agent; for capability-only calls this is whatever the
    # Hebbian router picked. Lets the frontend show "routed to: X" without
    # a second round-trip.
    agent_name: str | None = None
    # Per-candidate routing breakdown when the Hebbian router was used.
    # Shape matches HebbianRouter.RoutingDecision.to_dict():
    # {agent_name, alpha, fallback_from, candidates: [{name, composite,
    # hebbian_weight, hebbian_norm, blended}, ...]}.
    routing: Dict[str, Any] | None = None
    atp: Dict[str, Any] | None = None
    provenance_id: str | None = None
    provider: str | None = None
    fallback_used: bool | None = None
    model: str | None = None
    outcome_class: str | None = None
    learning_eligible: bool | None = None
    exo_request: Dict[str, Any] | None = None
    compressed_context: str | None = None
    output_compression: Dict[str, Any] | None = None


# SQLite paths -- align with the rest of the project, which writes to
# ``data/`` at the repo root (see src/api_bridge.py,
# src/launch/main.py and the PKG-INFO doc). The dashboard previously
# pointed at ``app/api/db/``, a directory that never gets populated, so
# every Database/Agents/Hebbian/Vector/Runs endpoint 500'd with
# "Database unavailable." Honor ``ARTEMIS_DATA_DIR`` as an umbrella
# override (useful for Docker), and the existing per-DB env names that
# api_bridge already documents.
DB_DIR = data_dir()
AGENT_REGISTRY_DB = Path(data_path("agent_registry.db", env_var="ARTEMIS_REGISTRY_DB"))
HEBBIAN_DB = Path(data_path("hebbian_weights.db", env_var="ARTEMIS_HEBBIAN_DB"))
VECTOR_DB = Path(data_path("vector_store.db", env_var="ARTEMIS_VECTOR_DB"))
RUN_LOG_DB = Path(data_path("run_logs.db", env_var="ARTEMIS_RUN_LOG_DB"))


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


def _get_vault_path() -> Path:
    vault_path = OBSIDIAN_VAULT_PATH or os.environ.get("OBSIDIAN_VAULT_PATH")
    if not vault_path:
        raise HTTPException(
            status_code=500, detail="Obsidian vault path not configured."
        )
    full_path = Path(vault_path).expanduser()
    if not full_path.is_dir():
        raise HTTPException(status_code=500, detail="Obsidian vault path not found.")
    return full_path


def _list_markdown_files(folder: Path) -> List[str]:
    if not folder.is_dir():
        return []
    return sorted(
        [f.name for f in folder.iterdir() if f.is_file() and f.suffix == ".md"]
    )


def _resolve_report_target(filename: str, vault_path: Path) -> tuple[Path, str]:
    """Resolve a report filename strictly inside the configured output folder."""
    requested = Path(filename)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("invalid report filename")

    vault_root = vault_path.resolve()
    output_dir = (vault_root / AGENT_OUTPUT_DIR).resolve()
    report_path = (output_dir / requested).resolve()
    try:
        report_path.relative_to(output_dir)
    except ValueError as exc:
        raise ValueError("report path escapes output directory") from exc
    return report_path, report_path.relative_to(vault_root).as_posix()


def _parse_task_note(content: str) -> Dict[str, Any] | None:
    """Parse task Markdown through the canonical Obsidian parser."""
    return ObsidianParser().parse_task_note(content)


def _list_all_task_records() -> list[dict[str, Any]]:
    """Load parseable task notes in every status for exact-ID lookups.

    ``GET /api/tasks`` intentionally remains the pending-task queue used by
    the executor. Detail pages need a separate read path so a task remains
    addressable after execution changes its status. The caller supplies only
    a task identifier; this helper enumerates configured task notes and never
    turns that identifier into a filesystem path.
    """
    if not orchestrator:
        vault_path = _get_vault_path()
        input_dir = vault_path / AGENT_INPUT_DIR
        records: list[dict[str, Any]] = []
        for filename in _list_markdown_files(input_dir):
            relative_path = f"{AGENT_INPUT_DIR}/{filename}"
            content = (input_dir / filename).read_text(encoding="utf-8")
            data = _parse_task_note(content)
            if not data:
                continue
            if "task_id" not in data:
                data["task_id"] = f"task_{hash(relative_path) % 100000}"
            records.append({**data, "relative_path": relative_path})
        return records

    records = []
    note_filenames = orchestrator.obs_manager.list_notes_in_folder(AGENT_INPUT_DIR)
    for filename in note_filenames:
        relative_path = os.path.join(AGENT_INPUT_DIR, filename)
        content = orchestrator.obs_manager.read_note(relative_path)
        if not content:
            continue
        data = orchestrator.obs_parser.parse_task_note(content)
        if not data:
            continue
        if "task_id" not in data:
            data["task_id"] = f"task_{hash(relative_path) % 100000}"
        records.append({**data, "relative_path": relative_path})
    return records


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
    orchestrator = None


async def startup_event():
    """Log FastAPI startup status for the dashboard service.

    Returns:
        None: This coroutine reports startup status through the configured logger.
    """
    if import_error:
        logger.warning(
            "Startup in SQLite-only mode due to import error: %s", import_error
        )
    if orchestrator:
        logger.info("FastAPI application starting up. Orchestrator ready.")
    else:
        logger.error(
            "FastAPI application starting up, but Orchestrator failed to initialize."
        )


app.router.add_event_handler("startup", startup_event)


# --- API Endpoints ---


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Container-level liveness probe.

    Unauthenticated by design so docker-compose / k8s healthchecks can
    reach it without provisioning an API key. Reports whether the
    orchestrator side-imported cleanly; SQLite-only mode is still
    considered live.
    """
    return {
        "status": "ok",
        "service": "artemis-kernel",
        "orchestrator": "ready" if orchestrator is not None else "sqlite-only",
    }


@app.get("/api/agents", response_model=List[AgentResponse])
async def get_agents(_key: None = Depends(_require_api_key)):
    """Return the registered agents exposed by the dashboard API.

    Returns only agents that are *live* in the running orchestrator (i.e.
    a Python instance was registered with a ``perform_task`` method).
    Falls back to the SQLite registry table when no orchestrator is
    attached. This filters out agents persisted by past test runs whose
    Python classes are not currently loaded -- picking one of those from
    the frontend dropdown would otherwise 400 with 'agent not found'.

    Args:
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        List[AgentResponse]: Registered agents loaded from the live
            orchestrator, or from the registry database as a fallback.
    """
    if orchestrator is not None:
        try:
            live_agents = orchestrator.agent_registry.get_all_agents()
            return [
                AgentResponse(
                    name=agent.name,
                    capabilities=list(getattr(agent, "capabilities", []) or []),
                )
                for agent in sorted(live_agents, key=lambda a: a.name)
            ]
        except Exception as e:
            logger.warning(
                "Live agent listing failed, falling back to registry DB: %s",
                _sanitize_for_log(e),
            )

    conn = _connect_db(AGENT_REGISTRY_DB)
    try:
        rows = conn.execute("""
            SELECT name, capabilities
            FROM agents
            ORDER BY name ASC
            """).fetchall()
        agents: List[AgentResponse] = []
        for row in rows:
            capabilities = _parse_json(row["capabilities"], [])
            if not isinstance(capabilities, list):
                capabilities = []
            agents.append(AgentResponse(name=row["name"], capabilities=capabilities))
        return agents
    except Exception as e:
        logger.error("Error fetching agents: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch agents.")
    finally:
        conn.close()


@app.get("/api/tasks")
async def get_tasks(_key: None = Depends(_require_api_key)):
    """Return pending task notes from Obsidian or the SQLite fallback mode.

    Args:
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        list[dict[str, Any]]: Serialized task records available for execution.
    """
    if not orchestrator:
        vault_path = _get_vault_path()
        input_dir = vault_path / AGENT_INPUT_DIR
        tasks = []
        for filename in _list_markdown_files(input_dir):
            relative_path = f"{AGENT_INPUT_DIR}/{filename}"
            content = (input_dir / filename).read_text(encoding="utf-8")
            data = _parse_task_note(content) or {}
            if "task_id" not in data:
                data["task_id"] = f"task_{hash(relative_path) % 100000}"
            tasks.append({**data, "relative_path": relative_path})
        return tasks
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


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, _key: None = Depends(_require_api_key)):
    """Return one task by exact task ID, regardless of execution status.

    The identifier is compared with parsed task metadata only. It is never
    concatenated with the vault root or passed to a note-read operation.
    """
    if not task_id or len(task_id) > 255:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        for task in _list_all_task_records():
            if str(task.get("task_id")) == task_id:
                return task
    except Exception as e:
        logger.error(
            "Error fetching task %s: %s",
            _sanitize_for_log(task_id),
            _sanitize_for_log(e),
        )
        raise HTTPException(status_code=500, detail="Failed to fetch task.")
    raise HTTPException(status_code=404, detail="Task not found.")


@app.get("/api/tasks/{task_id}/activity")
async def get_task_activity(
    task_id: str,
    limit: int = 200,
    _key: None = Depends(_require_api_key),
):
    """Return the governed activity trail for one exact task identifier.

    This is a read-only projection over task metadata, the canonical run log,
    and server-generated report summaries. The browser supplies only the task
    identifier; it cannot select a note path or report filename. Event
    metadata is parsed and matched by exact ``task_id`` before it is returned,
    so a similarly named task cannot borrow another task's provenance.
    """
    if not task_id or len(task_id) > 255:
        raise HTTPException(status_code=404, detail="Task activity not found.")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")

    try:
        task = next(
            (
                record
                for record in _list_all_task_records()
                if str(record.get("task_id")) == task_id
            ),
            None,
        )
    except Exception as e:
        logger.error(
            "Error resolving task activity record %s: %s",
            _sanitize_for_log(task_id),
            _sanitize_for_log(e),
        )
        raise HTTPException(status_code=500, detail="Failed to load task activity.")

    conn = _connect_db(RUN_LOG_DB)
    try:
        rows = conn.execute("""
            SELECT
              run_id,
              timestamp,
              event_type,
              component,
              message,
              metadata,
              duration_ms,
              prov_id,
              parent_prov_id
            FROM event_log
            ORDER BY created_at ASC, id ASC
            """).fetchall()
    except Exception as e:
        logger.error(
            "Error fetching task activity %s: %s",
            _sanitize_for_log(task_id),
            _sanitize_for_log(e),
        )
        raise HTTPException(status_code=500, detail="Failed to load task activity.")
    finally:
        conn.close()

    events: list[dict[str, Any]] = []
    for row in rows:
        metadata = _parse_json(row["metadata"], {})
        if not isinstance(metadata, dict) or str(metadata.get("task_id")) != task_id:
            continue
        events.append(
            {
                "run_id": row["run_id"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "component": row["component"],
                "message": row["message"],
                "metadata": metadata,
                "duration_ms": row["duration_ms"],
                "prov_id": row["prov_id"],
                "parent_prov_id": row["parent_prov_id"],
            }
        )
        if len(events) >= limit:
            break

    if task is None and not events:
        raise HTTPException(status_code=404, detail="Task activity not found.")

    routing: dict[str, Any] | None = None
    provenance_id: str | None = None
    agent_name: str | None = None
    capability: str | None = None
    provider: str | None = None
    outcome_class: str | None = None
    learning_eligible: bool | None = None
    status = str(task.get("status")) if task else None

    for event in events:
        metadata = event["metadata"]
        event_type = event["event_type"]
        if event_type == "prompt_received" and event["prov_id"]:
            provenance_id = str(event["prov_id"])
        elif provenance_id is None and event["prov_id"]:
            provenance_id = str(event["prov_id"])

        if event_type == "routing_decision":
            decision = metadata.get("decision")
            if isinstance(decision, dict):
                routing = decision
            agent_name = str(
                metadata.get("chosen_agent") or metadata.get("agent_name") or agent_name
            )
        if metadata.get("agent") or metadata.get("agent_name"):
            agent_name = str(metadata.get("agent") or metadata.get("agent_name"))
        if metadata.get("capability") or metadata.get("required_capability"):
            capability = str(
                metadata.get("capability") or metadata.get("required_capability")
            )
        if metadata.get("provider") is not None:
            provider = str(metadata["provider"])
        if metadata.get("outcome_class") is not None:
            outcome_class = str(metadata["outcome_class"])
        if metadata.get("learning_eligible") is not None:
            learning_eligible = bool(metadata["learning_eligible"])
        if metadata.get("status") is not None:
            status = str(metadata["status"])

    try:
        report_models = await get_reports()
        reports = [
            report.model_dump() for report in report_models if report.task_id == task_id
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error linking reports for task activity %s: %s",
            _sanitize_for_log(task_id),
            _sanitize_for_log(e),
        )
        raise HTTPException(status_code=500, detail="Failed to load task reports.")

    return {
        "task_id": task_id,
        "task": task,
        "status": status,
        "provenance_id": provenance_id,
        "agent_name": agent_name,
        "capability": capability,
        "routing": routing,
        "provider": provider,
        "outcome_class": outcome_class,
        "learning_eligible": learning_eligible,
        "reports": reports,
        "events": events,
    }


@app.post("/api/tasks", status_code=201)
async def create_task(task_data: TaskData, _key: None = Depends(_require_api_key)):
    """Create a new task note and return its routing metadata.

    Args:
        task_data (TaskData): Structured task payload to persist in Obsidian.
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        dict[str, Any]: Metadata describing the created task note and resolved capability.
    """
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    try:
        payload = task_data.model_dump()
        relative_path = orchestrator.create_new_task_in_obsidian(payload)
        resolved_capability = orchestrator._resolve_required_capability(payload)
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
    """Return summary metadata for stored agent reports.

    Args:
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        List[ReportSummary]: Report descriptors available in the output directory.
    """
    if not orchestrator:
        vault_path = _get_vault_path()
        output_dir = vault_path / AGENT_OUTPUT_DIR
        report_files = _list_markdown_files(output_dir)
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
    """Return the markdown content for a stored report.

    Args:
        filename (str): Report filename to load from the output directory.
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        dict[str, str]: Report filename and rendered markdown content.
    """
    manager_vault = getattr(
        getattr(orchestrator, "obs_manager", None), "vault_path", None
    )
    vault_path = (
        Path(manager_vault)
        if isinstance(manager_vault, (str, os.PathLike))
        else _get_vault_path()
    )
    try:
        report_path, relative_path = _resolve_report_target(filename, vault_path)
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid report filename.")

    if not orchestrator:
        if not report_path.is_file():
            raise HTTPException(status_code=404, detail="Report not found.")
        content = report_path.read_text(encoding="utf-8")
        return {"filename": filename, "content": content}
    try:
        content = orchestrator.obs_manager.read_note(relative_path)
        if content is None:
            raise HTTPException(status_code=404, detail="Report not found.")
        return {"filename": filename, "content": content}
    except ValueError:
        # obs_manager rejects absolute / traversal / vault-escaping paths.
        raise HTTPException(status_code=400, detail="Invalid report filename.")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error reading report %s: %s",
            _sanitize_for_log(filename),
            _sanitize_for_log(e),
        )
        raise HTTPException(status_code=500, detail="Failed to read report.")


@app.post("/api/execute-task")
async def execute_pending_task(
    task_path: Dict[str, str], _key: None = Depends(_require_api_key)
):
    """Execute a specific pending task note identified by its relative path.

    Args:
        task_path (Dict[str, str]): Request payload containing the task note path.
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        dict[str, Any]: Execution status message and the orchestrator result payload.
    """
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")

    relative_note_path = task_path.get("relative_path")
    if not relative_note_path:
        raise HTTPException(
            status_code=400, detail="Missing 'relative_path' in request body."
        )

    task_data: dict[str, Any] | None = None
    try:
        content = orchestrator.obs_manager.read_note(relative_note_path)
        if not content:
            raise HTTPException(status_code=404, detail="Task note not found.")

        task_data = orchestrator.obs_parser.parse_task_note(content)
        if not task_data or task_data.get("status", "pending").lower() != "pending":
            raise HTTPException(
                status_code=400, detail="Task is not pending or could not be parsed."
            )

        resolved_capability = orchestrator._resolve_required_capability(task_data)
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
        orchestrator.update_task_status_in_obsidian(
            relative_note_path,
            "failed",
            task_data.get("task_id") if task_data else None,
        )
        raise HTTPException(status_code=400, detail="Invalid task data.")
    except HTTPException:
        raise
    except Exception as e:
        if task_data is not None:
            orchestrator.update_task_status_in_obsidian(
                relative_note_path, "failed", task_data.get("task_id")
            )
        logger.error(
            "Error executing task from %s: %s",
            _sanitize_for_log(relative_note_path),
            _sanitize_for_log(e),
        )
        raise HTTPException(status_code=500, detail="Failed to execute task.")


@app.post("/api/execute-all-pending")
async def execute_all_pending_tasks(_key: None = Depends(_require_api_key)):
    """Execute every pending task discovered in the input directory.

    Args:
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        dict[str, Any]: Batch execution summary returned by the orchestrator.
    """
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
    """Return score and capability data for all registered agents.

    Args:
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        List[AgentScore]: Registry score records formatted for the dashboard.
    """
    conn = _connect_db(AGENT_REGISTRY_DB)
    try:
        rows = conn.execute("""
            SELECT
              name,
              capabilities,
              COALESCE(alignment, 0.0) AS alignment,
              COALESCE(accuracy, 0.0) AS accuracy,
              COALESCE(efficiency, 0.0) AS efficiency,
              trust_tier,
              status,
              COALESCE(violation_count, 0) AS violation_count,
              trust_score,
              COALESCE(execution_count, 0) AS execution_count,
              COALESCE(successful_executions, 0) AS successful_executions,
              COALESCE(failed_executions, 0) AS failed_executions,
              hebbian_weight,
              COALESCE(hebbian_delta, 0.0) AS hebbian_delta,
              COALESCE(hebbian_activations, 0) AS hebbian_activations,
              COALESCE(hebbian_success_rate, 0.0) AS hebbian_success_rate,
              hebbian_task_type,
              COALESCE(hebbian_pair_bonus, 0.0) AS hebbian_pair_bonus,
              hebbian_timing_score,
              COALESCE(routing_intelligence, 0.0) AS routing_intelligence,
              COALESCE(hebbian_oscillation_rate, 0.0) AS hebbian_oscillation_rate,
              COALESCE(hebbian_sentinel_alert, 0) AS hebbian_sentinel_alert,
              COALESCE(hebbian_sentinel_samples, 0) AS hebbian_sentinel_samples,
              learning_updated_at
            FROM agents
            ORDER BY name ASC
            """).fetchall()

        agents: List[AgentScore] = []
        for row in rows:
            capabilities = _parse_json(row["capabilities"], [])
            if not isinstance(capabilities, list):
                capabilities = []
            alignment = float(row["alignment"])
            accuracy = float(row["accuracy"])
            efficiency = float(row["efficiency"])
            composite = alignment * 0.4 + accuracy * 0.4 + efficiency * 0.2
            agents.append(
                AgentScore(
                    name=row["name"],
                    capabilities=capabilities,
                    alignment=alignment,
                    accuracy=accuracy,
                    efficiency=efficiency,
                    composite_score=composite,
                    trust_tier=row["trust_tier"] or "monitored",
                    status=row["status"] or "active",
                    violation_count=int(row["violation_count"]),
                    trust_score=(
                        float(row["trust_score"])
                        if row["trust_score"] is not None
                        else None
                    ),
                    execution_count=int(row["execution_count"]),
                    successful_executions=int(row["successful_executions"]),
                    failed_executions=int(row["failed_executions"]),
                    hebbian_weight=(
                        float(row["hebbian_weight"])
                        if row["hebbian_weight"] is not None
                        else None
                    ),
                    hebbian_delta=float(row["hebbian_delta"]),
                    hebbian_activations=int(row["hebbian_activations"]),
                    hebbian_success_rate=float(row["hebbian_success_rate"]),
                    hebbian_task_type=row["hebbian_task_type"],
                    hebbian_pair_bonus=float(row["hebbian_pair_bonus"]),
                    hebbian_timing_score=(
                        float(row["hebbian_timing_score"])
                        if row["hebbian_timing_score"] is not None
                        else None
                    ),
                    routing_intelligence=float(row["routing_intelligence"]),
                    hebbian_oscillation_rate=float(row["hebbian_oscillation_rate"]),
                    hebbian_sentinel_alert=bool(row["hebbian_sentinel_alert"]),
                    hebbian_sentinel_samples=int(row["hebbian_sentinel_samples"]),
                    learning_updated_at=row["learning_updated_at"],
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
    """Return aggregate Hebbian-network statistics.

    Args:
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        HebbianStats: Aggregate counts and success-rate metrics for the network.
    """
    conn = _connect_db(HEBBIAN_DB)
    try:
        row = conn.execute("""
            SELECT
              COUNT(*) AS total_connections,
              COALESCE(AVG(weight), 0.0) AS avg_weight,
              COALESCE(MAX(weight), 0.0) AS max_weight,
              COALESCE(SUM(activation_count), 0) AS total_activations,
              COALESCE(SUM(success_count), 0) AS total_successes
            FROM node_connections
            """).fetchone()
        # Aggregate SELECT without GROUP BY always yields one row; COALESCE
        # above supplies stable values for an empty table.
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
async def get_hebbian_connections(
    limit: int = 50, _key: None = Depends(_require_api_key)
):
    """Return the strongest Hebbian connections ordered by weight.

    Args:
        limit (int): Maximum number of connection rows to return.
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        List[HebbianConnection]: Ranked Hebbian connection records for inspection.
    """
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
                success_rate=_safe_rate(
                    int(row["success_count"]), int(row["activation_count"])
                ),
            )
            for row in rows
        ]
    except Exception as e:
        logger.error("Error fetching Hebbian connections: %s", _sanitize_for_log(e))
        raise HTTPException(
            status_code=500, detail="Failed to fetch Hebbian connections."
        )
    finally:
        conn.close()


@app.get("/api/db/hebbian/agent/{agent_name}")
async def get_agent_hebbian_stats(
    agent_name: str, _key: None = Depends(_require_api_key)
):
    """Return Hebbian statistics for a single agent node.

    Args:
        agent_name (str): Agent node to inspect in the Hebbian graph.
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        dict[str, Any]: Aggregate weights and strongest connections for the agent.
    """
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

        # Aggregate SELECT without GROUP BY always yields one row.
        avg_weight = float(stats_row["avg_weight"])
        total_activations = int(stats_row["total_activations"])
        total_successes = int(stats_row["total_successes"])

        return {
            "agent_name": agent_name,
            "average_weight": avg_weight,
            "success_rate": _safe_rate(total_successes, total_activations),
            "strongest_connections": [
                {"target": row["target_node"], "weight": float(row["weight"])}
                for row in top_rows
            ],
        }
    except Exception as e:
        logger.error("Error fetching agent Hebbian stats: %s", _sanitize_for_log(e))
        raise HTTPException(
            status_code=500, detail="Failed to fetch agent Hebbian stats."
        )
    finally:
        conn.close()


@app.get("/api/db/hebbian/sentinel")
async def get_hebbian_sentinel_status(
    agent_name: str | None = None,
    task_type: str | None = None,
    limit: int = 100,
    _key: None = Depends(_require_api_key),
):
    """Return current observational Hebbian stability signals."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    conn = _connect_db(HEBBIAN_DB)
    try:
        clauses = []
        params: List[Any] = []
        if agent_name:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        query = "SELECT * FROM hebbian_sentinel_state"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(
            query,
            tuple(params),
        ).fetchall()
        results = [dict(row) for row in rows]
        for result in results:
            result["alert_active"] = bool(result["alert_active"])
        return {"signals": results, "total": len(results)}
    except Exception as e:
        logger.error("Error fetching Hebbian sentinel: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch sentinel state.")
    finally:
        conn.close()


@app.get("/api/db/hebbian/sentinel/alerts")
async def get_hebbian_sentinel_alerts(
    open_only: bool = False,
    limit: int = 100,
    _key: None = Depends(_require_api_key),
):
    """Return persisted sentinel alert transitions for operator review."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    conn = _connect_db(HEBBIAN_DB)
    try:
        query = "SELECT * FROM hebbian_sentinel_alerts"
        if open_only:
            query += " WHERE status = 'open'"
        query += " ORDER BY id DESC LIMIT ?"
        rows = conn.execute(
            query,
            (limit,),
        ).fetchall()
        alerts = [dict(row) for row in rows]
        return {"alerts": alerts, "total": len(alerts)}
    except Exception as e:
        logger.error("Error fetching Hebbian sentinel alerts: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to fetch sentinel alerts.")
    finally:
        conn.close()


@app.get("/api/db/vectors/stats", response_model=VectorStoreStats)
async def get_vector_stats(_key: None = Depends(_require_api_key)):
    """Return aggregate statistics for the vector store database.

    Args:
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        VectorStoreStats: Document-count and average-content metrics for the store.
    """
    conn = _connect_db(VECTOR_DB)
    try:
        row = conn.execute("""
            SELECT
              COUNT(*) AS total_docs,
              COALESCE(AVG(LENGTH(COALESCE(content, ''))), 0.0) AS avg_content_length
            FROM vectors
            """).fetchone()
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
async def list_vectors(
    limit: int = 100, offset: int = 0, _key: None = Depends(_require_api_key)
):
    """Return paginated vector-store records for dashboard inspection.

    Args:
        limit (int): Maximum number of vector rows to return.
        offset (int): Zero-based offset for paginated browsing.
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        list[dict[str, Any]]: Paginated vector records with metadata and content previews.
    """
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
    """Return recent orchestration runs with summary metadata.

    Args:
        limit (int): Maximum number of runs to return.
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        List[RunSummary]: Recent run summaries ordered by recency.
    """
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
async def get_run_events_endpoint(
    run_id: str, event_type: str | None = None, _key: None = Depends(_require_api_key)
):
    """Return the recorded events for a specific orchestration run.

    Args:
        run_id (str): Identifier of the run to inspect.
        event_type (str | None): Optional event-type filter.
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        list[dict[str, Any]]: Serialized run events ordered by creation time.
    """
    conn = _connect_db(RUN_LOG_DB)
    try:
        query = """
            SELECT
              timestamp,
              event_type,
              component,
              message,
              metadata,
              duration_ms,
              prov_id,
              parent_prov_id
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
                    "prov_id": row["prov_id"],
                    "parent_prov_id": row["parent_prov_id"],
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
async def execute_instruction(
    request: ExecuteInstructionRequest, _key: None = Depends(_require_api_key)
):
    """Execute a CLI-style instruction through the orchestrator.

    Args:
        request (ExecuteInstructionRequest): Instruction payload submitted by the client.
        _key (None): Auth dependency result injected by FastAPI.

    Returns:
        ExecuteInstructionResponse: Structured execution status, summary, and note metadata.
    """
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")

    if not request.instruction.strip():
        raise HTTPException(status_code=400, detail="Instruction cannot be empty.")

    try:
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        task_id = f"user_instruction_{timestamp}"
        task_title = request.title or request.instruction.strip().split("\n")[0][:80]

        # Resolve capability and agent. ATP can supply the action domain when
        # the caller did not pin a capability.
        effective_capability = request.capability
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
        task_data: Dict[str, Any] = {
            "task_id": task_id,
            "title": task_title,
            "context": request.instruction,
            "content": request.instruction,
            "_capability_explicit": bool(effective_capability),
            "atp_strict": request.atp_strict,
            "status": "pending",
            "tags": ["user_instruction"],
        }
        if effective_capability:
            task_data["required_capability"] = effective_capability

        task_data = orchestrator.prepare_task_context(task_data)
        if not task_data.get("required_capability"):
            task_data["required_capability"] = "web_search"
        task_data.setdefault("routing_scope", task_data["required_capability"])
        task_data["tags"] = ["user_instruction", task_data["required_capability"]]
        if task_data.get("atp") and not request.title:
            task_data["title"] = (
                task_data["atp"].get("context") or task_data["title"]
            )[:80]
        task_data = orchestrator.ensure_task_provenance(
            task_data,
            source="fastapi.execute",
        )

        if agent_for_dispatch:
            task_data["agent"] = agent_for_dispatch.name

        # Create task in Obsidian
        note_path = None
        try:
            note_path = orchestrator.create_new_task_in_obsidian(task_data)
            orchestrator.update_task_status_in_obsidian(
                note_path, "in progress", task_id
            )
        except Exception as e:
            logger.error("Failed to create task in Obsidian: %s", _sanitize_for_log(e))

        # Execute task. For capability-only calls, route through the
        # Hebbian router first so we can surface the decision (chosen
        # agent + per-candidate blended scores) back to the frontend.
        # Routing is pure (no side effects) so calling it before
        # assign_and_execute_task does not double-execute the task.
        routing_decision = None
        try:
            if agent_for_dispatch:
                # User picked an agent explicitly; no Hebbian routing.
                chosen_agent_name = agent_for_dispatch.name
                orchestrator.log_routing_decision(
                    task_data,
                    chosen_agent_name,
                    source="fastapi.execute",
                    pinned=True,
                )
                result = await run_in_threadpool(
                    orchestrator.assign_and_execute_task,
                    chosen_agent_name,
                    task_data,
                    note_path,
                )
            elif orchestrator.hebbian_routing_enabled:
                routing_decision = orchestrator.hebbian_router.route(task_data)
                chosen_agent_name = routing_decision.agent_name
                orchestrator.log_routing_decision(
                    task_data,
                    chosen_agent_name,
                    decision=routing_decision,
                    source="fastapi.execute",
                )
                result = await run_in_threadpool(
                    orchestrator.assign_and_execute_task,
                    chosen_agent_name,
                    task_data,
                    note_path,
                )
            else:
                chosen_agent_name = orchestrator.agent_registry.route_task(task_data)
                orchestrator.log_routing_decision(
                    task_data,
                    chosen_agent_name,
                    source="fastapi.execute",
                )
                result = await run_in_threadpool(
                    orchestrator.assign_and_execute_task,
                    chosen_agent_name,
                    task_data,
                    note_path,
                )

            execution_failed = result.get("status") == "failed"
            return ExecuteInstructionResponse(
                task_id=task_id,
                status="failed" if execution_failed else "success",
                summary=result.get("summary", "Task executed"),
                note_path=note_path,
                error=result.get("error") if execution_failed else None,
                agent_name=chosen_agent_name,
                routing=routing_decision.to_dict() if routing_decision else None,
                atp=task_data.get("atp"),
                provenance_id=task_data.get("provenance_id"),
                provider=result.get("provider"),
                fallback_used=result.get("fallback_used"),
                model=result.get("model"),
                outcome_class=result.get("outcome_class"),
                learning_eligible=result.get("learning_eligible"),
                exo_request=result.get("exo_request"),
                compressed_context=result.get("compressed_context"),
                output_compression=result.get("output_compression"),
            )
        except Exception as e:
            # Log the real exception server-side; never echo exception
            # details (which may carry stack/context) back to the client.
            logger.error("Error executing instruction: %s", _sanitize_for_log(e))
            if note_path:
                orchestrator.update_task_status_in_obsidian(
                    note_path, "failed", task_id
                )
            return ExecuteInstructionResponse(
                task_id=task_id,
                status="failed",
                summary="Task execution failed",
                note_path=note_path,
                error="Task execution failed; see server logs",
                agent_name=None,
                routing=routing_decision.to_dict() if routing_decision else None,
                atp=task_data.get("atp"),
                provenance_id=task_data.get("provenance_id"),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error processing instruction: %s", _sanitize_for_log(e))
        raise HTTPException(status_code=500, detail="Failed to process instruction.")


@app.post("/api/cli/execute/stream")
async def execute_instruction_stream(
    request: ExecuteInstructionRequest, _key: None = Depends(_require_api_key)
):
    """Stream a routing + execution flow as Server-Sent Events.

    Event sequence:
        event: routing   data: {decision: {...}, agent_name: "..."}
        event: token     data: {text: "..."}              (zero or more)
        event: complete  data: {task_id, summary, note_path, status, error}
        event: error     data: {error: "..."}             (terminal on failure)

    The LLM agent streams real Exo tokens; other agents emit a single
    token event with the full summary so the client UI doesn't have to
    branch on agent type. The orchestrator's normal post-processing
    (memory bus persist, Hebbian update, Obsidian status update) still
    runs after the stream completes.
    """
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized.")
    active_orchestrator = orchestrator
    if not request.instruction.strip():
        raise HTTPException(status_code=400, detail="Instruction cannot be empty.")

    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    task_id = f"user_instruction_{timestamp}"
    task_title = request.title or request.instruction.strip().split("\n")[0][:80]

    effective_capability = request.capability
    if request.agent:
        agent_obj = active_orchestrator.agent_registry.get_agent(request.agent)
        if not agent_obj:
            raise HTTPException(status_code=400, detail="Specified agent not found.")
        if not request.capability and agent_obj.capabilities:
            effective_capability = agent_obj.capabilities[0]

    task_data: Dict[str, Any] = {
        "task_id": task_id,
        "title": task_title,
        "context": request.instruction,
        "content": request.instruction,
        "_capability_explicit": bool(effective_capability),
        "atp_strict": request.atp_strict,
        "status": "pending",
        "tags": ["user_instruction"],
    }
    if effective_capability:
        task_data["required_capability"] = effective_capability
    task_data = active_orchestrator.prepare_task_context(task_data)
    if not task_data.get("required_capability"):
        task_data["required_capability"] = "web_search"
    task_data.setdefault("routing_scope", task_data["required_capability"])
    task_data["tags"] = ["user_instruction", task_data["required_capability"]]
    if task_data.get("atp") and not request.title:
        task_data["title"] = (task_data["atp"].get("context") or task_data["title"])[
            :80
        ]
    task_data = active_orchestrator.ensure_task_provenance(
        task_data,
        source="fastapi.execute.stream",
    )
    if request.agent:
        task_data["agent"] = request.agent

    # Create the Obsidian note before the stream starts, so the run is
    # auditable even if the stream is dropped mid-flight.
    note_path = None
    try:
        note_path = active_orchestrator.create_new_task_in_obsidian(task_data)
        active_orchestrator.update_task_status_in_obsidian(
            note_path, "in progress", task_id
        )
    except Exception as e:
        logger.error(
            "Failed to create streaming task in Obsidian: %s", _sanitize_for_log(e)
        )

    def _sse_pack(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    def _stream():
        # Execute orchestration in its own worker so this generator can emit
        # heartbeat comments while Exo is still thinking. This keeps proxies
        # and browsers from treating a legitimate long inference as a dead
        # connection. The daemon worker also finishes persistence/learning if
        # the client disconnects after dispatch.
        import queue
        import threading

        event_queue: queue.Queue[Any] = queue.Queue()
        finished = object()
        consumer_closed = threading.Event()

        def _produce() -> None:
            try:
                for item in active_orchestrator.stream_route_and_execute(
                    task_data, note_path
                ):
                    # Keep advancing the governed execution after disconnect so
                    # persistence and learning still finish, but do not retain an
                    # unbounded token backlog once nobody can consume it.
                    if not consumer_closed.is_set():
                        event_queue.put(item)
            except Exception:  # noqa: BLE001
                logger.error("Streaming executor worker crashed.", exc_info=True)
                if not consumer_closed.is_set():
                    event_queue.put(
                        {
                            "type": "error",
                            "error": "Streaming executor crashed; see server logs.",
                        }
                    )
            finally:
                if not consumer_closed.is_set():
                    event_queue.put(finished)

        threading.Thread(target=_produce, daemon=True).start()
        try:
            heartbeat_seconds = max(
                1.0, float(os.getenv("ARTEMIS_SSE_HEARTBEAT_SECONDS", "15"))
            )
        except ValueError:
            heartbeat_seconds = 15.0

        terminal_sent = False
        try:
            while True:
                try:
                    ev = event_queue.get(timeout=heartbeat_seconds)
                except queue.Empty:
                    yield ": artemis-heartbeat\n\n"
                    continue

                if ev is finished:
                    if not terminal_sent:
                        yield _sse_pack(
                            "error",
                            {
                                "error": "Execution ended before a terminal event; "
                                "see server logs."
                            },
                        )
                    return

                if not isinstance(ev, dict):
                    continue
                etype = ev.get("type")
                if etype == "routing":
                    yield _sse_pack(
                        "routing",
                        {
                            "decision": ev.get("decision"),
                            "agent_name": ev.get("agent_name"),
                            "task_id": task_id,
                            "atp": task_data.get("atp"),
                            "provenance_id": task_data.get("provenance_id"),
                        },
                    )
                elif etype == "token":
                    yield _sse_pack("token", {"text": ev.get("text", "")})
                elif etype == "complete":
                    terminal_sent = True
                    yield _sse_pack(
                        "complete",
                        {
                            "task_id": ev.get("task_id"),
                            "agent_name": ev.get("agent_name"),
                            "status": ev.get("status"),
                            "summary": ev.get("summary"),
                            "note_path": ev.get("note_path"),
                            "error": ev.get("error"),
                            "atp": ev.get("atp"),
                            "provenance_id": ev.get("provenance_id"),
                            "provider": ev.get("provider"),
                            "fallback_used": ev.get("fallback_used"),
                            "model": ev.get("model"),
                            "outcome_class": ev.get("outcome_class"),
                            "learning_eligible": ev.get("learning_eligible"),
                            "exo_request": ev.get("exo_request"),
                            "compressed_context": ev.get("compressed_context"),
                            "output_compression": ev.get("output_compression"),
                        },
                    )
                elif etype == "error":
                    terminal_sent = True
                    yield _sse_pack("error", {"error": ev.get("error", "")})
        except GeneratorExit:
            # The worker deliberately continues to finalize the governed task
            # even when a browser closes the stream.
            return
        except Exception:  # noqa: BLE001
            logger.error("Streaming event encoder crashed.", exc_info=True)
            yield _sse_pack(
                "error",
                {"error": "Streaming executor crashed; see server logs."},
            )
        finally:
            consumer_closed.set()

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            # Disable proxy buffering so tokens arrive promptly.
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
