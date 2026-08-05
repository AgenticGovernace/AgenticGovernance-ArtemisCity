"""Focused contract tests for the FastAPI dashboard service.

The dashboard is deliberately outside the wheel's production ``src`` package,
so these tests import it against temporary runtime directories and replace the
orchestrator for every request.  No repository database, Obsidian vault, model,
or network service is used.
"""

from __future__ import annotations

import builtins
import importlib
import importlib.util
import logging
import sqlite3
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def dashboard_module(tmp_path_factory: pytest.TempPathFactory):
    """Import the dashboard once with all persistent paths redirected."""
    root = tmp_path_factory.mktemp("dashboard-import")
    vault = root / "vault"
    (vault / "Agent Inputs").mkdir(parents=True)
    (vault / "Agent Outputs").mkdir(parents=True)

    patch = pytest.MonkeyPatch()
    patch.setenv("ARTEMIS_DATA_DIR", str(root / "data"))
    patch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    patch.setenv("AGENT_INPUT_DIR", "Agent Inputs")
    patch.setenv("AGENT_OUTPUT_DIR", "Agent Outputs")
    patch.setenv("ANACONDA_AGENT_PORTS", "")
    patch.setenv("FASTAPI_CORS_ORIGINS", "https://one.example, https://two.example ,")
    patch.delenv("FASTAPI_API_KEY", raising=False)
    patch.delenv("MCP_API_KEY", raising=False)
    sys.modules.pop("app.api.main", None)
    module = importlib.import_module("app.api.main")
    module.AGENT_INPUT_DIR = "Agent Inputs"
    module.AGENT_OUTPUT_DIR = "Agent Outputs"
    yield module
    module.app.dependency_overrides.clear()
    patch.undo()


@pytest.fixture
def dashboard(dashboard_module, monkeypatch: pytest.MonkeyPatch):
    """Restore safe request defaults for each dashboard test."""
    monkeypatch.setattr(dashboard_module, "orchestrator", None)
    monkeypatch.setattr(dashboard_module, "_FASTAPI_API_KEY", None)
    dashboard_module.app.dependency_overrides.clear()
    return dashboard_module


@pytest.fixture
def client(dashboard):
    with TestClient(dashboard.app) as test_client:
        yield test_client


@pytest.fixture
def dashboard_db(tmp_path: Path, dashboard, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create the complete dashboard-facing SQLite schema with representative data."""
    db_path = tmp_path / "dashboard.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE agents (
            name TEXT,
            capabilities TEXT,
            alignment REAL,
            accuracy REAL,
            efficiency REAL,
            trust_tier TEXT,
            status TEXT,
            violation_count INTEGER,
            trust_score REAL,
            execution_count INTEGER,
            successful_executions INTEGER,
            failed_executions INTEGER,
            hebbian_weight REAL,
            hebbian_delta REAL,
            hebbian_activations INTEGER,
            hebbian_success_rate REAL,
            hebbian_task_type TEXT,
            hebbian_pair_bonus REAL,
            hebbian_timing_score REAL,
            routing_intelligence REAL,
            hebbian_oscillation_rate REAL,
            hebbian_sentinel_alert INTEGER,
            hebbian_sentinel_samples INTEGER,
            learning_updated_at TEXT
        );
        CREATE TABLE node_connections (
            origin_node TEXT,
            target_node TEXT,
            weight REAL,
            activation_count INTEGER,
            success_count INTEGER,
            failure_count INTEGER
        );
        CREATE TABLE hebbian_sentinel_state (
            agent_name TEXT,
            task_type TEXT,
            alert_active INTEGER,
            updated_at TEXT
        );
        CREATE TABLE hebbian_sentinel_alerts (
            id INTEGER PRIMARY KEY,
            agent_name TEXT,
            status TEXT,
            created_at TEXT
        );
        CREATE TABLE vectors (
            doc_id TEXT,
            metadata TEXT,
            content TEXT
        );
        CREATE TABLE event_log (
            id INTEGER PRIMARY KEY,
            run_id TEXT,
            timestamp TEXT,
            event_type TEXT,
            component TEXT,
            message TEXT,
            metadata TEXT,
            duration_ms REAL,
            prov_id TEXT,
            parent_prov_id TEXT,
            created_at TEXT
        );
        """)
    conn.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "Alpha",
            '["search", "reasoning"]',
            0.8,
            0.6,
            0.5,
            "trusted",
            "active",
            2,
            0.75,
            10,
            7,
            3,
            1.4,
            0.2,
            8,
            0.875,
            "web_search",
            0.1,
            0.9,
            0.82,
            0.12,
            1,
            12,
            "2026-07-14T12:00:00",
        ),
    )
    conn.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "Beta",
            "{}",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
    )
    conn.executemany(
        "INSERT INTO node_connections VALUES (?,?,?,?,?,?)",
        [
            ("Alpha", "summary", 1.5, 4, 3, 1),
            ("Alpha", "research", 0.7, 0, 0, 0),
            (None, None, None, None, None, None),
        ],
    )
    conn.executemany(
        "INSERT INTO hebbian_sentinel_state VALUES (?,?,?,?)",
        [
            ("Alpha", "web_search", 1, "2026-07-14T12:00:00"),
            ("Beta", "summary", 0, "2026-07-14T11:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO hebbian_sentinel_alerts VALUES (?,?,?,?)",
        [
            (1, "Alpha", "closed", "2026-07-14T10:00:00"),
            (2, "Beta", "open", "2026-07-14T11:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO vectors VALUES (?,?,?)",
        [
            ("doc-1", '{"source": "vault"}', "hello"),
            ("doc-2", '["unexpected"]', None),
        ],
    )
    conn.executemany(
        "INSERT INTO event_log VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                1,
                "run-1",
                "2026-07-14T10:00:00",
                "routing",
                "router",
                "selected Alpha",
                '{"score": 0.9}',
                2.5,
                "prov-1",
                None,
                "2026-07-14T10:00:00",
            ),
            (
                2,
                "run-1",
                "2026-07-14T10:01:00",
                "completion",
                "agent",
                "done",
                "invalid-json",
                None,
                "prov-2",
                "prov-1",
                "2026-07-14T10:01:00",
            ),
            (
                3,
                "run-2",
                "2026-07-14T11:00:00",
                "failure",
                "agent",
                "failed",
                None,
                1.0,
                "prov-3",
                None,
                "2026-07-14T11:00:00",
            ),
        ],
    )
    conn.commit()
    conn.close()

    for name in ("AGENT_REGISTRY_DB", "HEBBIAN_DB", "VECTOR_DB", "RUN_LOG_DB"):
        monkeypatch.setattr(dashboard, name, db_path)
    return db_path


class _Decision:
    agent_name = "Routed Agent"

    def to_dict(self):
        return {"agent_name": self.agent_name, "candidates": []}


class _Registry:
    def __init__(self, agent=None, routed_name: str = "Legacy Agent"):
        self.agent = agent
        self.routed_name = routed_name

    def get_agent(self, name):
        if self.agent is not None and name == self.agent.name:
            return self.agent
        return None

    def get_all_agents(self):
        return [] if self.agent is None else [self.agent]

    def route_task(self, _task_data):
        return self.routed_name


class _Orchestrator:
    """Small behaviorally complete fake for dashboard endpoint contracts."""

    def __init__(self, *, agent=None, hebbian: bool = True):
        self.agent_registry = _Registry(agent)
        self.hebbian_routing_enabled = hebbian
        self.hebbian_router = SimpleNamespace(route=lambda _task: _Decision())
        self.obs_manager = MagicMock()
        self.obs_parser = MagicMock()
        self.status_updates = []
        self.routing_logs = []
        self.assigned = []
        self.created = []

    def prepare_task_context(self, task):
        return task

    def ensure_task_provenance(self, task, *, source):
        return {**task, "provenance_id": f"prov:{source}"}

    def create_new_task_in_obsidian(self, task):
        self.created.append(task)
        return f"Agent Inputs/{task['task_id']}.md"

    def update_task_status_in_obsidian(self, path, status, task_id):
        self.status_updates.append((path, status, task_id))

    def _resolve_required_capability(self, task):
        return task.get("required_capability") or task.get("capability") or "web_search"

    def log_routing_decision(self, task, agent_name, **details):
        self.routing_logs.append((task, agent_name, details))

    def assign_and_execute_task(self, name, task, note_path):
        self.assigned.append((name, task, note_path))
        return {
            "status": "success",
            "summary": "completed",
            "provider": "exo",
            "fallback_used": False,
            "model": "model-a",
            "outcome_class": "success",
            "learning_eligible": True,
            "exo_request": {"request_id": "req-a", "http_status": 200},
            "compressed_context": "completed",
            "output_compression": {"status": "completed", "agent": "Summary A"},
        }

    def route_and_execute_task(self, task, note_path):
        return {"status": "success", "summary": "routed", "path": note_path}

    def check_for_new_tasks_from_obsidian(self):
        return [("Agent Inputs/live.md", {"title": "Live"})]

    def execute_all_pending_tasks(self):
        return {"executed": 2}

    def stream_route_and_execute(self, task, note_path):
        yield {"type": "routing", "decision": {"agent": "Alpha"}, "agent_name": "Alpha"}
        yield {"type": "token", "text": "hello"}
        yield {
            "type": "complete",
            "task_id": task["task_id"],
            "agent_name": "Alpha",
            "status": "success",
            "summary": "hello",
            "note_path": note_path,
            "error": None,
            "atp": task.get("atp"),
            "provenance_id": task.get("provenance_id"),
            "provider": "exo",
            "fallback_used": False,
            "model": "model-a",
            "outcome_class": "success",
            "learning_eligible": True,
            "exo_request": {"request_id": "req-stream", "http_status": 200},
            "compressed_context": "hello",
            "output_compression": {"status": "completed", "agent": "Summary A"},
        }


def test_helpers_cover_sanitization_parsing_rates_and_task_notes(
    dashboard, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        dashboard, "_shared_sanitize_for_log", lambda value: f"safe:{value}"
    )
    assert dashboard._sanitize_for_log("value") == "safe:value"
    monkeypatch.setattr(dashboard, "_shared_sanitize_for_log", None)
    assert dashboard._sanitize_for_log("a\r\nb") == "ab"

    fallback = object()
    value = {"already": "parsed"}
    assert dashboard._parse_json(None, fallback) is fallback
    assert dashboard._parse_json(value, fallback) is value
    assert dashboard._parse_json(7, fallback) is fallback
    assert dashboard._parse_json('{"ok": true}', fallback) == {"ok": True}
    assert dashboard._parse_json("bad-json", fallback) is fallback
    assert dashboard._safe_rate(3, 4) == 0.75
    assert dashboard._safe_rate(1, 0) == 0.0

    note = dashboard._parse_task_note("""---
task_id: T-1
status: pending
---
# A title
Context: Case facts
plain text that is intentionally ignored
- [ ] first
- [x] second
""")
    assert note == {
        "task_id": "T-1",
        "status": "pending",
        "title": "A title",
        "context": "Case facts",
        "subtasks": [
            {"text": "first", "completed": False},
            {"text": "second", "completed": True},
        ],
    }
    assert dashboard._parse_task_note("\n\n") is None


def test_import_fallback_and_orchestrator_constructor_failure(
    tmp_path: Path, dashboard, monkeypatch: pytest.MonkeyPatch
):
    """Exercise both documented SQLite-only import paths in isolated modules."""

    def load_copy(name: str):
        spec = importlib.util.spec_from_file_location(name, dashboard.__file__)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            return module
        finally:
            sys.modules.pop(name, None)

    monkeypatch.setenv("ARTEMIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))

    original_sys_path = list(sys.path)
    repo_root = str(dashboard._REPO_ROOT)
    monkeypatch.setattr(
        sys, "path", [entry for entry in sys.path if entry != repo_root]
    )
    path_bootstrap = load_copy("_dashboard_path_bootstrap")
    assert str(path_bootstrap._REPO_ROOT) == path_bootstrap.sys.path[0]
    monkeypatch.setattr(sys, "path", original_sys_path)

    real_import = builtins.__import__

    def fail_core_config(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "src.mcp.config":
            raise ImportError("core intentionally unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_core_config)
    fallback = load_copy("_dashboard_sqlite_fallback")
    assert fallback.Orchestrator is None
    assert fallback.orchestrator is None
    assert isinstance(fallback.import_error, ImportError)
    assert fallback.startup_event in fallback.app.router.on_startup

    fallback_logger = logging.getLogger("mcp_dashboard_api")
    handler = logging.NullHandler()
    fallback_logger.addHandler(handler)
    try:
        fallback_with_configured_logger = load_copy("_dashboard_configured_logger")
        assert fallback_with_configured_logger.orchestrator is None
    finally:
        fallback_logger.removeHandler(handler)

    monkeypatch.setattr(builtins, "__import__", real_import)
    fake_orchestrator_module = ModuleType("src.mcp.orchestrator")

    class BrokenOrchestrator:
        def __init__(self):
            raise RuntimeError("constructor failed")

    fake_orchestrator_module.Orchestrator = BrokenOrchestrator
    monkeypatch.setitem(sys.modules, "src.mcp.orchestrator", fake_orchestrator_module)
    constructor_failure = load_copy("_dashboard_constructor_failure")
    assert constructor_failure.Orchestrator is BrokenOrchestrator
    assert constructor_failure.orchestrator is None
    assert constructor_failure.import_error is None


def test_vault_helpers_validate_paths_and_list_only_markdown(
    tmp_path: Path, dashboard, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(dashboard, "OBSIDIAN_VAULT_PATH", "")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    with pytest.raises(HTTPException, match="not configured") as exc_info:
        dashboard._get_vault_path()
    assert exc_info.value.status_code == 500

    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "missing"))
    with pytest.raises(HTTPException, match="not found"):
        dashboard._get_vault_path()

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    assert dashboard._get_vault_path() == vault
    assert dashboard._list_markdown_files(vault / "absent") == []
    (vault / "b.md").write_text("b", encoding="utf-8")
    (vault / "a.md").write_text("a", encoding="utf-8")
    (vault / "ignore.txt").write_text("x", encoding="utf-8")
    (vault / "folder.md").mkdir()
    assert dashboard._list_markdown_files(vault) == ["a.md", "b.md"]


def test_health_openapi_authentication_and_startup_contract(
    dashboard, dashboard_db: Path, monkeypatch: pytest.MonkeyPatch
):
    assert dashboard.app.title == "MCP Obsidian API"
    assert dashboard.app.version == "0.1.0"
    assert dashboard._cors_origins == [
        "https://one.example",
        "https://two.example",
    ]
    # The lifecycle function is part of the service contract and must be wired.
    assert dashboard.startup_event in dashboard.app.router.on_startup

    with TestClient(dashboard.app) as test_client:
        assert test_client.get("/health").json()["orchestrator"] == "sqlite-only"
        assert test_client.get("/openapi.json").json()["info"]["version"] == "0.1.0"
        preflight = test_client.options(
            "/api/agents",
            headers={
                "Origin": "https://one.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "https://one.example"

        monkeypatch.setattr(dashboard, "_FASTAPI_API_KEY", "secret")
        assert test_client.get("/health").status_code == 200
        assert test_client.get("/api/agents").status_code == 401
        assert (
            test_client.get("/api/agents", headers={"X-API-Key": "wrong"}).status_code
            == 401
        )
        response = test_client.get("/api/agents", headers={"X-API-Key": "secret"})
        assert response.status_code == 200
        assert response.json()[0] == {
            "name": "Alpha",
            "capabilities": ["search", "reasoning"],
        }

    monkeypatch.setattr(dashboard, "orchestrator", object())
    with TestClient(dashboard.app) as test_client:
        assert test_client.get("/health").json()["orchestrator"] == "ready"


@pytest.mark.parametrize(
    ("import_error", "orchestrator", "expected_method"),
    [
        (RuntimeError("core unavailable"), None, "warning"),
        (None, object(), "info"),
        (None, None, "error"),
    ],
)
def test_startup_event_reports_each_runtime_mode(
    dashboard,
    monkeypatch: pytest.MonkeyPatch,
    import_error,
    orchestrator,
    expected_method,
):
    logger = MagicMock()
    monkeypatch.setattr(dashboard, "logger", logger)
    monkeypatch.setattr(dashboard, "import_error", import_error)
    monkeypatch.setattr(dashboard, "orchestrator", orchestrator)
    import asyncio

    asyncio.run(dashboard.startup_event())
    assert getattr(logger, expected_method).called


def test_fallback_tasks_reports_and_safe_report_reads(
    tmp_path: Path, dashboard, monkeypatch: pytest.MonkeyPatch
):
    vault = tmp_path / "vault"
    input_dir = vault / "Agent Inputs"
    output_dir = vault / "Agent Outputs"
    input_dir.mkdir(parents=True)
    output_dir.mkdir()
    (input_dir / "task.md").write_text(
        "---\ntask_id: T1\nstatus: pending\n---\n# Work", encoding="utf-8"
    )
    (input_dir / "untagged.md").write_text("# Untagged", encoding="utf-8")
    (output_dir / "Alpha_Report_T1_2.md").write_text("# report", encoding="utf-8")
    (output_dir / "odd.md").write_text("odd", encoding="utf-8")
    (vault / "secret.md").write_text("secret", encoding="utf-8")
    (output_dir / "linked").symlink_to(vault, target_is_directory=True)
    monkeypatch.setattr(dashboard, "OBSIDIAN_VAULT_PATH", str(vault))

    with TestClient(dashboard.app) as test_client:
        tasks = test_client.get("/api/tasks")
        assert tasks.status_code == 200
        assert [task["relative_path"] for task in tasks.json()] == [
            "Agent Inputs/task.md",
            "Agent Inputs/untagged.md",
        ]
        assert tasks.json()[1]["task_id"].startswith("task_")
        task_detail = test_client.get("/api/tasks/T1")
        assert task_detail.status_code == 200
        assert task_detail.json()["relative_path"] == "Agent Inputs/task.md"
        assert task_detail.json()["status"] == "pending"
        assert test_client.get("/api/tasks/missing").status_code == 404
        assert test_client.get("/api/tasks/%2E%2E%2Fsecret").status_code == 404

        reports = test_client.get("/api/reports")
        assert reports.status_code == 200
        assert reports.json() == [
            {
                "filename": "Alpha_Report_T1_2.md",
                "agent": "Alpha",
                "task_id": "T1",
                "timestamp": "N/A",
            },
            {
                "filename": "odd.md",
                "agent": "unknown_agent",
                "task_id": "unknown_task",
                "timestamp": "N/A",
            },
        ]
        assert test_client.get("/api/reports/Alpha_Report_T1_2.md").json() == {
            "filename": "Alpha_Report_T1_2.md",
            "content": "# report",
        }
        assert test_client.get("/api/reports/missing.md").status_code == 404
        traversal = test_client.get("/api/reports/%2E%2E%2Fsecret.md")
        assert traversal.status_code == 400
        assert traversal.json() == {"detail": "Invalid report filename."}
        symlink_escape = test_client.get("/api/reports/linked/secret.md")
        assert symlink_escape.status_code == 400
        assert symlink_escape.json() == {"detail": "Invalid report filename."}


def test_live_agents_tasks_reports_and_creation(
    dashboard, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    agent = SimpleNamespace(name="Zed", capabilities=["reasoning"])
    other = SimpleNamespace(name="Alpha", capabilities=None)
    orch = _Orchestrator(agent=agent)
    orch.agent_registry.get_all_agents = lambda: [agent, other]
    orch.obs_manager.list_notes_in_folder.return_value = [
        "Zed_Report_T9_4.md",
        "unstructured.md",
    ]
    orch.obs_manager.read_note.return_value = "# live report"
    monkeypatch.setattr(dashboard, "orchestrator", orch)

    assert client.get("/api/agents").json() == [
        {"name": "Alpha", "capabilities": []},
        {"name": "Zed", "capabilities": ["reasoning"]},
    ]
    tasks = client.get("/api/tasks").json()
    assert tasks[0]["title"] == "Live"
    assert tasks[0]["task_id"].startswith("task_")
    orch.check_for_new_tasks_from_obsidian = lambda: [
        ("Agent Inputs/identified.md", {"task_id": "T-existing", "title": "Known"})
    ]
    identified = client.get("/api/tasks").json()
    assert identified[0]["task_id"] == "T-existing"
    reports = client.get("/api/reports").json()
    assert reports[0]["task_id"] == "T9"
    assert reports[1]["agent"] == "unknown_agent"
    assert client.get("/api/reports/live.md").json()["content"] == "# live report"
    orch.obs_manager.read_note.assert_called_with("Agent Outputs/live.md")
    orch.obs_manager.read_note.reset_mock()
    traversal = client.get("/api/reports/%2E%2E%2Fsecret.md")
    assert traversal.status_code == 400
    orch.obs_manager.read_note.assert_not_called()

    created = client.post(
        "/api/tasks",
        json={"task_id": "T9", "agent": "Zed", "required_capability": "reasoning"},
    )
    assert created.status_code == 201
    assert created.json()["required_capability"] == "reasoning"


def test_live_task_detail_finds_completed_task_by_exact_id(
    dashboard, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    orch = _Orchestrator()
    orch.obs_manager.list_notes_in_folder.return_value = ["completed.md"]
    orch.obs_manager.read_note.return_value = "---\ntask_id: T-done\nstatus: completed\n---\n# Done"
    orch.obs_parser.parse_task_note.return_value = {
        "task_id": "T-done",
        "status": "completed",
        "title": "Done",
    }
    monkeypatch.setattr(dashboard, "orchestrator", orch)

    response = client.get("/api/tasks/T-done")
    assert response.status_code == 200
    assert response.json() == {
        "task_id": "T-done",
        "status": "completed",
        "title": "Done",
        "relative_path": "Agent Inputs/completed.md",
    }
    orch.obs_manager.read_note.assert_called_once_with("Agent Inputs/completed.md")
    assert client.get("/api/tasks/missing").status_code == 404


def test_live_endpoint_error_contracts(
    dashboard,
    dashboard_db: Path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    orch = _Orchestrator()
    orch.agent_registry.get_all_agents = MagicMock(
        side_effect=RuntimeError("registry\nfailed")
    )
    monkeypatch.setattr(dashboard, "orchestrator", orch)
    # Agent listing degrades to SQLite when the live registry fails.
    assert client.get("/api/agents").status_code == 200

    orch.check_for_new_tasks_from_obsidian = MagicMock(side_effect=RuntimeError("boom"))
    assert client.get("/api/tasks").json() == {"detail": "Failed to fetch tasks."}
    orch.create_new_task_in_obsidian = MagicMock(side_effect=RuntimeError("boom"))
    assert client.post("/api/tasks", json={"agent": "Alpha"}).status_code == 500
    orch.obs_manager.list_notes_in_folder.side_effect = RuntimeError("boom")
    assert client.get("/api/reports").status_code == 500

    orch.obs_manager.read_note.side_effect = ValueError("traversal")
    assert client.get("/api/reports/bad.md").status_code == 400
    orch.obs_manager.read_note.side_effect = FileNotFoundError()
    assert client.get("/api/reports/missing.md").status_code == 404
    orch.obs_manager.read_note.side_effect = RuntimeError("boom")
    assert client.get("/api/reports/failure.md").status_code == 500
    orch.obs_manager.read_note.side_effect = None
    orch.obs_manager.read_note.return_value = None
    assert client.get("/api/reports/none.md").status_code == 404


def test_unavailable_orchestrator_rejects_mutating_endpoints(client: TestClient):
    assert client.post("/api/tasks", json={"agent": "Alpha"}).status_code == 500
    assert (
        client.post("/api/execute-task", json={"relative_path": "x.md"}).status_code
        == 500
    )
    assert client.post("/api/execute-all-pending").status_code == 500
    assert (
        client.post("/api/cli/execute", json={"instruction": "work"}).status_code == 500
    )
    assert (
        client.post("/api/cli/execute/stream", json={"instruction": "work"}).status_code
        == 500
    )


def test_execute_pending_task_direct_and_capability_routes(
    dashboard, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    agent = SimpleNamespace(name="Alpha", capabilities=["search"])
    orch = _Orchestrator(agent=agent)
    monkeypatch.setattr(dashboard, "orchestrator", orch)

    assert client.post("/api/execute-task", json={}).status_code == 400
    orch.obs_manager.read_note.return_value = None
    assert (
        client.post("/api/execute-task", json={"relative_path": "x.md"}).status_code
        == 404
    )
    orch.obs_manager.read_note.return_value = "task"
    orch.obs_parser.parse_task_note.return_value = {"status": "complete"}
    assert (
        client.post("/api/execute-task", json={"relative_path": "x.md"}).status_code
        == 400
    )

    orch.obs_parser.parse_task_note.return_value = {
        "task_id": "T1",
        "status": "pending",
        "agent": "Alpha",
        "required_capability": "search",
    }
    direct = client.post("/api/execute-task", json={"relative_path": "x.md"})
    assert direct.status_code == 200
    assert direct.json()["results"]["summary"] == "completed"

    orch.obs_parser.parse_task_note.return_value = {
        "task_id": "T2",
        "status": "pending",
        "agent": "Missing",
        "required_capability": "search",
    }
    routed = client.post("/api/execute-task", json={"relative_path": "y.md"})
    assert routed.status_code == 200
    assert routed.json()["results"]["summary"] == "routed"

    orch._resolve_required_capability = lambda _task: None
    orch.obs_parser.parse_task_note.return_value = {
        "task_id": "T3",
        "status": "pending",
    }
    no_capability = client.post("/api/execute-task", json={"relative_path": "z.md"})
    assert no_capability.status_code == 400
    assert orch.status_updates[-1][1] == "no_capability"


def test_execute_pending_and_batch_error_paths(
    dashboard, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    orch = _Orchestrator()
    orch.obs_manager.read_note.return_value = "task"
    orch.obs_parser.parse_task_note.return_value = {
        "task_id": "T1",
        "status": "pending",
        "required_capability": "search",
    }
    orch.route_and_execute_task = MagicMock(side_effect=ValueError("invalid"))
    monkeypatch.setattr(dashboard, "orchestrator", orch)
    invalid = client.post("/api/execute-task", json={"relative_path": "x.md"})
    assert invalid.status_code == 400
    assert orch.status_updates[-1][1] == "failed"

    orch.route_and_execute_task.side_effect = RuntimeError("crashed")
    failed = client.post("/api/execute-task", json={"relative_path": "x.md"})
    assert failed.status_code == 500

    # A read failure happens before task parsing; there is no task status to update.
    orch.obs_manager.read_note.side_effect = RuntimeError("read failed")
    before = list(orch.status_updates)
    failed_early = client.post("/api/execute-task", json={"relative_path": "x.md"})
    assert failed_early.status_code == 500
    assert orch.status_updates == before

    orch.execute_all_pending_tasks = MagicMock(return_value={"executed": 3})
    assert client.post("/api/execute-all-pending").json() == {"executed": 3}
    orch.execute_all_pending_tasks.side_effect = RuntimeError("crashed")
    assert client.post("/api/execute-all-pending").status_code == 500


def test_database_inspection_success_contracts(dashboard_db: Path, client: TestClient):
    agents = client.get("/api/db/agents")
    assert agents.status_code == 200
    assert agents.json()[0]["composite_score"] == pytest.approx(0.66)
    assert agents.json()[0]["hebbian_sentinel_alert"] is True
    assert agents.json()[1]["capabilities"] == []
    assert agents.json()[1]["trust_tier"] == "monitored"

    stats = client.get("/api/db/hebbian/stats").json()
    assert stats["total_connections"] == 3
    assert stats["total_activations"] == 4
    assert stats["success_rate"] == 0.75
    connections = client.get("/api/db/hebbian/connections?limit=2").json()
    assert connections[0]["origin_node"] == "Alpha"
    assert connections[0]["success_rate"] == 0.75
    assert connections[1]["success_rate"] == 0.0
    per_agent = client.get("/api/db/hebbian/agent/Alpha").json()
    assert per_agent["success_rate"] == 0.75
    assert len(per_agent["strongest_connections"]) == 2

    signals = client.get(
        "/api/db/hebbian/sentinel?agent_name=Alpha&task_type=web_search&limit=5"
    ).json()
    assert signals["total"] == 1
    assert signals["signals"][0]["alert_active"] is True
    injected_filter = client.get(
        "/api/db/hebbian/sentinel",
        params={"agent_name": "Alpha' OR 1=1 --", "limit": 5},
    ).json()
    assert injected_filter == {"signals": [], "total": 0}
    alerts = client.get("/api/db/hebbian/sentinel/alerts?open_only=true&limit=5").json()
    assert alerts["total"] == 1
    assert alerts["alerts"][0]["status"] == "open"

    vector_stats = client.get("/api/db/vectors/stats").json()
    assert vector_stats == {"total_docs": 2, "avg_content_length": 2.5}
    vectors = client.get("/api/db/vectors/list?limit=2&offset=0").json()
    assert vectors[0]["metadata"] == {"source": "vault"}
    assert vectors[1]["metadata"] == {"raw": '["unexpected"]'}
    assert vectors[1]["content"] == ""

    runs = client.get("/api/db/runs?limit=5").json()
    assert runs[0]["run_id"] == "run-2"
    assert runs[1]["total_events"] == 2
    events = client.get("/api/db/runs/run-1/events?event_type=routing").json()
    assert len(events) == 1
    assert events[0]["metadata"] == {"score": 0.9}
    all_events = client.get("/api/db/runs/run-1/events").json()
    assert all_events[1]["metadata"] == {}


@pytest.mark.parametrize(
    "path",
    [
        "/api/db/hebbian/connections?limit=0",
        "/api/db/hebbian/sentinel?limit=0",
        "/api/db/hebbian/sentinel?limit=501",
        "/api/db/hebbian/sentinel/alerts?limit=0",
        "/api/db/hebbian/sentinel/alerts?limit=501",
        "/api/db/vectors/list?limit=0",
        "/api/db/vectors/list?offset=-1",
        "/api/db/runs?limit=0",
    ],
)
def test_database_query_validation(path: str, dashboard_db: Path, client: TestClient):
    response = client.get(path)
    assert response.status_code == 400


def test_database_missing_and_schema_error_paths(
    tmp_path: Path, dashboard, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(dashboard, "AGENT_REGISTRY_DB", missing)
    response = client.get("/api/db/agents")
    assert response.status_code == 500
    assert response.json() == {"detail": "Database unavailable."}

    malformed = tmp_path / "malformed.db"
    sqlite3.connect(malformed).close()
    monkeypatch.setattr(dashboard, "AGENT_REGISTRY_DB", malformed)
    response = client.get("/api/agents")
    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to fetch agents."}

    response = client.get("/api/db/agents")
    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to fetch agent scores."}


@pytest.mark.parametrize(
    ("db_name", "path", "detail"),
    [
        ("HEBBIAN_DB", "/api/db/hebbian/stats", "Failed to fetch Hebbian stats."),
        (
            "HEBBIAN_DB",
            "/api/db/hebbian/connections",
            "Failed to fetch Hebbian connections.",
        ),
        (
            "HEBBIAN_DB",
            "/api/db/hebbian/agent/Alpha",
            "Failed to fetch agent Hebbian stats.",
        ),
        (
            "HEBBIAN_DB",
            "/api/db/hebbian/sentinel",
            "Failed to fetch sentinel state.",
        ),
        (
            "HEBBIAN_DB",
            "/api/db/hebbian/sentinel/alerts",
            "Failed to fetch sentinel alerts.",
        ),
        ("VECTOR_DB", "/api/db/vectors/stats", "Failed to fetch vector stats."),
        ("VECTOR_DB", "/api/db/vectors/list", "Failed to list vectors."),
        ("RUN_LOG_DB", "/api/db/runs", "Failed to fetch runs."),
        (
            "RUN_LOG_DB",
            "/api/db/runs/run-1/events",
            "Failed to fetch run events.",
        ),
    ],
)
def test_database_endpoint_schema_errors_are_stable(
    db_name: str,
    path: str,
    detail: str,
    tmp_path: Path,
    dashboard,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    malformed = tmp_path / f"{db_name}.db"
    sqlite3.connect(malformed).close()
    monkeypatch.setattr(dashboard, db_name, malformed)
    response = client.get(path)
    assert response.status_code == 500
    assert response.json() == {"detail": detail}


def test_cli_execute_pinned_hebbian_and_legacy_routing(
    dashboard, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    agent = SimpleNamespace(name="Pinned Agent", capabilities=["reasoning"])
    orch = _Orchestrator(agent=agent)
    monkeypatch.setattr(dashboard, "orchestrator", orch)

    assert (
        client.post("/api/cli/execute", json={"instruction": "   "}).status_code == 400
    )
    assert (
        client.post(
            "/api/cli/execute", json={"instruction": "work", "agent": "Missing"}
        ).status_code
        == 400
    )

    pinned = client.post(
        "/api/cli/execute",
        json={"instruction": "reason about this", "agent": "Pinned Agent"},
    )
    assert pinned.status_code == 200
    assert pinned.json()["agent_name"] == "Pinned Agent"
    assert pinned.json()["routing"] is None
    assert pinned.json()["provenance_id"] == "prov:fastapi.execute"
    assert pinned.json()["provider"] == "exo"
    assert pinned.json()["fallback_used"] is False
    assert pinned.json()["model"] == "model-a"
    assert pinned.json()["outcome_class"] == "success"
    assert pinned.json()["learning_eligible"] is True
    assert pinned.json()["exo_request"]["request_id"] == "req-a"
    assert pinned.json()["output_compression"]["agent"] == "Summary A"
    assert orch.routing_logs[-1][2]["pinned"] is True

    explicit_capability = client.post(
        "/api/cli/execute",
        json={
            "instruction": "reason again",
            "agent": "Pinned Agent",
            "capability": "custom",
            "title": "Explicit title",
        },
    )
    assert explicit_capability.status_code == 200
    assert orch.created[-1]["required_capability"] == "custom"
    assert orch.created[-1]["title"] == "Explicit title"

    routed = client.post("/api/cli/execute", json={"instruction": "find sources"})
    assert routed.status_code == 200
    assert routed.json()["agent_name"] == "Routed Agent"
    assert routed.json()["routing"]["agent_name"] == "Routed Agent"

    orch.hebbian_routing_enabled = False
    legacy = client.post("/api/cli/execute", json={"instruction": "legacy"})
    assert legacy.status_code == 200
    assert legacy.json()["agent_name"] == "Legacy Agent"

    def add_atp(task):
        return {**task, "atp": {"context": "ATP-derived title"}}

    orch.prepare_task_context = add_atp
    atp = client.post("/api/cli/execute", json={"instruction": "ATP payload"})
    assert atp.status_code == 200
    assert orch.created[-1]["title"] == "ATP-derived title"


def test_cli_execute_failure_is_sanitized_and_note_failure_is_nonfatal(
    dashboard, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    orch = _Orchestrator()
    orch.create_new_task_in_obsidian = MagicMock(
        side_effect=RuntimeError("vault offline")
    )
    orch.assign_and_execute_task = MagicMock(
        return_value={"status": "failed", "summary": "no model", "error": "offline"}
    )
    monkeypatch.setattr(dashboard, "orchestrator", orch)
    response = client.post("/api/cli/execute", json={"instruction": "work"})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["note_path"] is None

    orch.hebbian_router.route = MagicMock(side_effect=RuntimeError("routing offline"))
    no_note_crash = client.post("/api/cli/execute", json={"instruction": "work"})
    assert no_note_crash.status_code == 200
    assert no_note_crash.json()["note_path"] is None
    assert no_note_crash.json()["error"] == "Task execution failed; see server logs"

    orch.create_new_task_in_obsidian.side_effect = None
    orch.create_new_task_in_obsidian.return_value = "Agent Inputs/task.md"
    orch.hebbian_router.route = MagicMock(side_effect=RuntimeError("secret\ntrace"))
    crashed = client.post("/api/cli/execute", json={"instruction": "work"})
    assert crashed.status_code == 200
    assert crashed.json()["error"] == "Task execution failed; see server logs"
    assert orch.status_updates[-1][1] == "failed"

    orch.prepare_task_context = MagicMock(side_effect=RuntimeError("bad ATP"))
    processing = client.post("/api/cli/execute", json={"instruction": "work"})
    assert processing.status_code == 500
    assert processing.json() == {"detail": "Failed to process instruction."}


def test_cli_stream_emits_every_event_and_sanitizes_crashes(
    dashboard, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    agent = SimpleNamespace(name="Pinned Agent", capabilities=["reasoning"])
    orch = _Orchestrator(agent=agent)
    monkeypatch.setattr(dashboard, "orchestrator", orch)

    assert (
        client.post("/api/cli/execute/stream", json={"instruction": " "}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/cli/execute/stream",
            json={"instruction": "work", "agent": "Missing"},
        ).status_code
        == 400
    )

    response = client.post(
        "/api/cli/execute/stream",
        json={"instruction": "stream", "agent": "Pinned Agent"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    body = response.text
    assert "event: routing" in body
    assert "event: token" in body
    assert "event: complete" in body
    assert "event: error" not in body
    assert '"text": "hello"' in body
    assert '"request_id": "req-stream"' in body
    assert '"fallback_used": false' in body
    assert '"learning_eligible": true' in body
    assert '"output_compression": {"status": "completed"' in body

    explicit_capability = client.post(
        "/api/cli/execute/stream",
        json={
            "instruction": "stream explicit",
            "agent": "Pinned Agent",
            "capability": "custom",
            "title": "Stream title",
        },
    )
    assert explicit_capability.status_code == 200
    assert orch.created[-1]["required_capability"] == "custom"
    assert orch.created[-1]["title"] == "Stream title"

    def error_stream(_task, _note_path):
        yield {"type": "error", "error": "model stopped"}

    orch.stream_route_and_execute = error_stream
    terminal_error = client.post(
        "/api/cli/execute/stream", json={"instruction": "stream error"}
    )
    assert "event: error" in terminal_error.text
    assert '"error": "model stopped"' in terminal_error.text

    def add_atp(task):
        return {**task, "atp": {"context": "Stream ATP title"}}

    orch.prepare_task_context = add_atp
    with_atp = client.post(
        "/api/cli/execute/stream", json={"instruction": "stream ATP"}
    )
    assert with_atp.status_code == 200
    assert orch.created[-1]["title"] == "Stream ATP title"

    def broken_stream(_task, _note_path):
        raise RuntimeError("private/path\ntrace")
        yield  # pragma: no cover - makes this a generator

    orch.stream_route_and_execute = broken_stream
    crashed = client.post("/api/cli/execute/stream", json={"instruction": "stream"})
    assert "Streaming executor crashed; see server logs." in crashed.text
    assert "private/path" not in crashed.text


def test_cli_stream_note_creation_failure_remains_streamable(
    dashboard, client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    orch = _Orchestrator()
    orch.create_new_task_in_obsidian = MagicMock(
        side_effect=RuntimeError("vault offline")
    )
    monkeypatch.setattr(dashboard, "orchestrator", orch)
    response = client.post("/api/cli/execute/stream", json={"instruction": "stream"})
    assert response.status_code == 200
    assert '"note_path": null' in response.text


def test_connect_db_sets_row_factory(dashboard_db: Path, dashboard):
    conn = dashboard._connect_db(dashboard_db)
    try:
        row = conn.execute("SELECT name FROM agents ORDER BY name LIMIT 1").fetchone()
        assert row["name"] == "Alpha"
    finally:
        conn.close()
