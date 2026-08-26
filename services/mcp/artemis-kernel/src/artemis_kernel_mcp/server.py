"""MCP transport adapter for the Artemis City Kernel task surface.

A pure factory, matching the discipline the artemis-validation server is held
to: no environment reads, no module-level server singleton, no I/O at import.
Everything impure lives in ``wiring`` and ``__main__``.

Each tool corresponds to one Kernel API operation in the Artemis City request
flow. Failures raise ``MCPError`` whose ``data`` carries the canonical error
envelope — ``{"error": {"code", "message", "request_id"}}`` — so an MCP client
sees a real protocol error and still receives the same envelope the HTTP
surface returns.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, Never

from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    ToolAnnotations,
)
from pydantic import ValidationError

from src.agents.atp.atp_models import ATPMode, ATPPriority

from .models import (
    CancelTaskInput,
    CreateTaskInput,
    GetTaskInput,
    ListTasksInput,
    Task,
    TaskListResult,
    TaskStatus,
    UpdateTaskStatusInput,
)
from .service import KernelError, TaskStore

_NON_STDIO_DISABLED = "kernel_non_stdio_transport_disabled"

_MUTATING = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def _envelope(code: str, message: str) -> dict[str, Any]:
    """The Artemis City error envelope, with a fresh correlation id."""
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": str(uuid.uuid4()),
        }
    }


def _invalid_input_error() -> MCPError:
    return MCPError(
        INVALID_PARAMS,
        "Invalid kernel tool input.",
        _envelope("invalid_kernel_input", "Invalid kernel tool input."),
    )


def _domain_error(error: KernelError) -> MCPError:
    return MCPError(INVALID_PARAMS, error.message, _envelope(error.code, error.message))


def _service_error() -> MCPError:
    message = "Kernel task service failed."
    return MCPError(INTERNAL_ERROR, message, _envelope("kernel_service_failed", message))


class _KernelMCPServer(MCPServer):
    """Stdio-only, mirroring the transport posture of the validation server."""

    def __init__(self) -> None:
        super().__init__(
            name="artemis-kernel",
            title="Artemis City Kernel",
            description="Task lifecycle operations for the Artemis City kernel.",
            version="0.1.0",
        )

    def run(
        self,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        **kwargs: Any,
    ) -> None:
        if transport == "sse":
            raise RuntimeError(_NON_STDIO_DISABLED)
        super().run(transport=transport, **kwargs)

    def sse_app(self, **kwargs: Any) -> Never:
        del kwargs
        raise RuntimeError(_NON_STDIO_DISABLED)

    async def run_sse_async(self, **kwargs: Any) -> Never:
        del kwargs
        raise RuntimeError(_NON_STDIO_DISABLED)


def create_server(*, service: TaskStore | None = None) -> MCPServer:
    """Build the Kernel MCP server over an injected task store."""
    store = service if service is not None else TaskStore()
    mcp_server = _KernelMCPServer()

    def _run[ResultT](operation) -> ResultT:
        """Translate domain failures; never leak an adapter's raw exception."""
        try:
            return operation()
        except KernelError as error:
            raise _domain_error(error) from None
        except MCPError:
            raise
        except Exception:  # noqa: BLE001
            raise _service_error() from None

    @mcp_server.tool(
        name="create-task",
        title="Create Task",
        description="Create a kernel task with ATP mode and priority.",
        annotations=_MUTATING,
        structured_output=True,
    )
    def create_task(
        description: str,
        mode: ATPMode = ATPMode.BUILD,
        priority: ATPPriority = ATPPriority.NORMAL,
        target_zone: str = "",
        assigned_agent: str = "",
    ) -> Task:
        try:
            request = CreateTaskInput(
                description=description,
                mode=mode,
                priority=priority,
                target_zone=target_zone,
                assigned_agent=assigned_agent,
            )
        except ValidationError:
            raise _invalid_input_error() from None
        return _run(
            lambda: store.create(
                description=request.description,
                mode=request.mode,
                priority=request.priority,
                target_zone=request.target_zone,
                assigned_agent=request.assigned_agent,
            )
        )

    @mcp_server.tool(
        name="get-task",
        title="Get Task",
        description="Fetch one kernel task by id.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def get_task(task_id: str) -> Task:
        try:
            request = GetTaskInput(task_id=task_id)
        except ValidationError:
            raise _invalid_input_error() from None
        return _run(lambda: store.get(request.task_id))

    @mcp_server.tool(
        name="cancel-task",
        title="Cancel Task",
        description="Cancel a pending or running kernel task.",
        annotations=_MUTATING,
        structured_output=True,
    )
    def cancel_task(task_id: str, reason: str = "") -> Task:
        try:
            request = CancelTaskInput(task_id=task_id, reason=reason)
        except ValidationError:
            raise _invalid_input_error() from None
        return _run(lambda: store.cancel(request.task_id, request.reason))

    @mcp_server.tool(
        name="list-tasks",
        title="List Tasks",
        description="List kernel tasks, newest first, optionally filtered.",
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def list_tasks(
        status: TaskStatus | None = None,
        assigned_agent: str = "",
        limit: int = 50,
    ) -> TaskListResult:
        try:
            request = ListTasksInput(
                status=status, assigned_agent=assigned_agent, limit=limit
            )
        except ValidationError:
            raise _invalid_input_error() from None

        def listed() -> TaskListResult:
            tasks, total = store.list(
                status=request.status,
                assigned_agent=request.assigned_agent,
                limit=request.limit,
            )
            return TaskListResult(tasks=tasks, total=total, limit=request.limit)

        return _run(listed)

    @mcp_server.tool(
        name="update-task-status",
        title="Update Task Status",
        description="Advance a task through its lifecycle states.",
        annotations=_MUTATING,
        structured_output=True,
    )
    def update_task_status(
        task_id: str,
        status: TaskStatus,
        result_summary: str = "",
    ) -> Task:
        try:
            request = UpdateTaskStatusInput(
                task_id=task_id, status=status, result_summary=result_summary
            )
        except ValidationError:
            raise _invalid_input_error() from None
        return _run(
            lambda: store.update_status(
                request.task_id, request.status, request.result_summary
            )
        )

    return mcp_server
