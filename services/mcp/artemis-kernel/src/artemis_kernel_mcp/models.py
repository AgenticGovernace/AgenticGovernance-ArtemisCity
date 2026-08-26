"""Typed contracts for the Kernel task surface.

The Agent Studio original returned bare ``dict`` from every ``@tool`` and
signalled failure with ``{"error": "..."}``. Both are replaced here: inputs are
strict Pydantic models so the MCP SDK can publish a real input schema, and
failures raise ``MCPError`` carrying the Artemis City error envelope instead of
being smuggled back as a success payload a caller can silently ignore.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from src.agents.atp.atp_models import ATPMode, ATPPriority

_MAX_TEXT = 4096
_MAX_LIMIT = 500


class TaskStatus(StrEnum):
    """Lifecycle states: pending -> running -> completed | failed | cancelled."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


class _Strict(BaseModel):
    """Reject unknown keys so a typo is a validation error, not a silent no-op."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Task(_Strict):
    """One kernel task. Timestamps are timezone-aware UTC."""

    task_id: str
    description: str
    mode: ATPMode
    priority: ATPPriority
    status: TaskStatus
    target_zone: str = ""
    assigned_agent: str = ""
    created_at: datetime
    updated_at: datetime
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None
    cancel_reason: str = ""
    result_summary: str = ""


class CreateTaskInput(_Strict):
    description: str = Field(min_length=1, max_length=_MAX_TEXT)
    mode: ATPMode = ATPMode.BUILD
    priority: ATPPriority = ATPPriority.NORMAL
    target_zone: str = Field(default="", max_length=_MAX_TEXT)
    assigned_agent: str = Field(default="", max_length=_MAX_TEXT)


class GetTaskInput(_Strict):
    task_id: str = Field(min_length=1, max_length=_MAX_TEXT)


class CancelTaskInput(_Strict):
    task_id: str = Field(min_length=1, max_length=_MAX_TEXT)
    reason: str = Field(default="", max_length=_MAX_TEXT)


class ListTasksInput(_Strict):
    status: TaskStatus | None = None
    assigned_agent: str = Field(default="", max_length=_MAX_TEXT)
    limit: int = Field(default=50, ge=1, le=_MAX_LIMIT)


class UpdateTaskStatusInput(_Strict):
    task_id: str = Field(min_length=1, max_length=_MAX_TEXT)
    status: TaskStatus
    result_summary: str = Field(default="", max_length=_MAX_TEXT)


class TaskListResult(_Strict):
    """Explicit total so a caller can tell a truncated page from a full one."""

    tasks: tuple[Task, ...]
    total: int
    limit: int
