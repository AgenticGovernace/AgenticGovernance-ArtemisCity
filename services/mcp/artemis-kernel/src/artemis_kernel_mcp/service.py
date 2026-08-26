"""Task storage for the Kernel surface.

Replaces the Agent Studio module-level ``_tasks`` dict plus its import-time
``_load_tasks()`` call. State now belongs to an instance the caller owns and
injects, so a test can construct an isolated store and importing the package
touches no disk.

Persistence keeps the original JSON-file format so an existing
``kernel_tasks.json`` is readable, but writes go through a temp file and
``os.replace`` — the original truncated the real file before serialising, so a
crash mid-write lost every task.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    TERMINAL_STATUSES,
    ATPMode,
    ATPPriority,
    Task,
    TaskStatus,
)


class KernelError(Exception):
    """Base for domain failures carrying a stable, safe code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TaskNotFound(KernelError):
    def __init__(self, task_id: str) -> None:
        super().__init__("task_not_found", f"Task not found: {task_id}")


class TaskNotCancellable(KernelError):
    def __init__(self, status: TaskStatus) -> None:
        super().__init__(
            "task_not_cancellable", f"Cannot cancel task in status: {status}"
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TaskStore:
    """In-memory task index with optional JSON-file durability."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._tasks: dict[str, Task] = {}

    def load(self) -> None:
        """Read persisted tasks. Missing or unreadable state starts empty."""
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        for task_id, payload in raw.items():
            try:
                self._tasks[task_id] = Task.model_validate(payload)
            except Exception:  # noqa: BLE001 - one bad record must not lose the rest
                continue

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            task_id: task.model_dump(mode="json")
            for task_id, task in self._tasks.items()
        }
        tmp = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def create(
        self,
        *,
        description: str,
        mode: ATPMode,
        priority: ATPPriority,
        target_zone: str,
        assigned_agent: str,
    ) -> Task:
        now = _utc_now()
        task = Task(
            task_id=str(uuid.uuid4()),
            description=description,
            mode=mode,
            priority=priority,
            status=TaskStatus.PENDING,
            target_zone=target_zone,
            assigned_agent=assigned_agent,
            created_at=now,
            updated_at=now,
        )
        self._tasks[task.task_id] = task
        self._save()
        return task

    def get(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        return task

    def cancel(self, task_id: str, reason: str) -> Task:
        task = self.get(task_id)
        if task.status in TERMINAL_STATUSES:
            raise TaskNotCancellable(task.status)
        now = _utc_now()
        updated = task.model_copy(
            update={
                "status": TaskStatus.CANCELLED,
                "cancelled_at": now,
                "updated_at": now,
                "cancel_reason": reason,
            }
        )
        self._tasks[task_id] = updated
        self._save()
        return updated

    def update_status(
        self, task_id: str, status: TaskStatus, result_summary: str
    ) -> Task:
        task = self.get(task_id)
        now = _utc_now()
        changes: dict[str, Any] = {"status": status, "updated_at": now}
        if status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            changes["completed_at"] = now
        elif status is TaskStatus.CANCELLED:
            changes["cancelled_at"] = now
        if result_summary:
            changes["result_summary"] = result_summary
        updated = task.model_copy(update=changes)
        self._tasks[task_id] = updated
        self._save()
        return updated

    def list(
        self,
        *,
        status: TaskStatus | None,
        assigned_agent: str,
        limit: int,
    ) -> tuple[tuple[Task, ...], int]:
        """Return one page newest-first plus the total before truncation."""
        matches = [
            task
            for task in self._tasks.values()
            if (status is None or task.status is status)
            and (not assigned_agent or task.assigned_agent == assigned_agent)
        ]
        matches.sort(key=lambda task: task.created_at, reverse=True)
        return tuple(matches[:limit]), len(matches)
