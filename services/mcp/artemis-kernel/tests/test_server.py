"""Contract tests for the artemis-kernel MCP adapter."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from artemis_kernel_mcp.models import TaskStatus
from artemis_kernel_mcp.server import create_server
from artemis_kernel_mcp.service import TaskStore
from mcp.shared.exceptions import MCPError

from mcp import Client
from src.agents.atp.atp_models import ATPMode, ATPPriority

EXPECTED_TOOLS = {
    "create-task",
    "get-task",
    "cancel-task",
    "list-tasks",
    "update-task-status",
}


def _server(tmp_path: Path | None = None):
    store = TaskStore(tmp_path / "kernel_tasks.json" if tmp_path else None)
    return create_server(service=store), store


def test_server_module_reads_no_environment_and_has_no_singleton() -> None:
    module = importlib.import_module("artemis_kernel_mcp.server")
    assert not hasattr(module, "server")
    assert not hasattr(module, "main")
    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    assert "os.getenv" not in source
    assert "os.environ" not in source


@pytest.mark.asyncio
async def test_tools_list_matches_the_kernel_api_surface() -> None:
    server, _ = _server()
    async with Client(server) as client:
        listed = await client.list_tools()
    assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS
    for tool in listed.tools:
        assert tool.output_schema is not None
        assert tool.annotations is not None


def test_task_lifecycle_pending_to_completed(tmp_path: Path) -> None:
    _, store = _server(tmp_path)
    task = store.create(
        description="ship the kernel adapter",
        mode=ATPMode.BUILD,
        priority=ATPPriority.HIGH,
        target_zone="services/mcp",
        assigned_agent="codex",
    )
    assert task.status is TaskStatus.PENDING
    running = store.update_status(task.task_id, TaskStatus.RUNNING, "")
    assert running.status is TaskStatus.RUNNING
    assert running.completed_at is None
    done = store.update_status(task.task_id, TaskStatus.COMPLETED, "shipped")
    assert done.status is TaskStatus.COMPLETED
    assert done.completed_at is not None
    assert done.result_summary == "shipped"


def test_cancel_rejects_terminal_tasks(tmp_path: Path) -> None:
    from artemis_kernel_mcp.service import TaskNotCancellable, TaskNotFound

    _, store = _server(tmp_path)
    task = store.create(
        description="t", mode=ATPMode.BUILD, priority=ATPPriority.NORMAL,
        target_zone="", assigned_agent="",
    )
    store.update_status(task.task_id, TaskStatus.COMPLETED, "")
    with pytest.raises(TaskNotCancellable):
        store.cancel(task.task_id, "too late")
    with pytest.raises(TaskNotFound):
        store.get("no-such-task")


def test_list_filters_and_reports_total_before_truncation(tmp_path: Path) -> None:
    _, store = _server(tmp_path)
    for index in range(5):
        store.create(
            description=f"task {index}", mode=ATPMode.BUILD,
            priority=ATPPriority.NORMAL, target_zone="",
            assigned_agent="alice" if index % 2 == 0 else "bob",
        )
    page, total = store.list(status=None, assigned_agent="alice", limit=2)
    assert total == 3
    assert len(page) == 2
    empty, zero = store.list(status=TaskStatus.FAILED, assigned_agent="", limit=10)
    assert empty == () and zero == 0


def test_state_survives_reload_and_write_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "kernel_tasks.json"
    store = TaskStore(path)
    created = store.create(
        description="persisted", mode=ATPMode.REVIEW, priority=ATPPriority.CRITICAL,
        target_zone="zone", assigned_agent="agent",
    )
    reloaded = TaskStore(path)
    reloaded.load()
    assert reloaded.get(created.task_id).description == "persisted"
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(path.read_text())[created.task_id]["priority"] == "Critical"


@pytest.mark.asyncio
async def test_missing_task_returns_the_artemis_error_envelope() -> None:
    server, _ = _server()
    async with Client(server) as client:
        with pytest.raises(MCPError) as raised:
            await client.call_tool("get-task", {"task_id": "missing"})
    envelope = raised.value.error.data["error"]
    assert envelope["code"] == "task_not_found"
    assert envelope["request_id"]
