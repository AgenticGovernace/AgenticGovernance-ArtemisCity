"""Environment wiring for the artemis-kernel MCP server.

``server.create_server`` never reads the environment; this module is the only
place that does, and nothing here runs at import time.
"""

from __future__ import annotations

import os
from pathlib import Path

from .service import TaskStore

_DATA_DIR_VAR = "ARTEMIS_DATA_DIR"
_DEFAULT_DATA_DIR = "data"
_TASKS_FILENAME = "kernel_tasks.json"


class KernelServerConfigurationError(RuntimeError):
    """Raised when required deployment configuration is missing or invalid."""


def build_task_store() -> TaskStore:
    """Build the task store and load any persisted tasks.

    Keeps the Agent Studio on-disk layout (``$ARTEMIS_DATA_DIR/kernel_tasks.json``)
    so an existing task file is picked up unchanged.
    """
    data_dir = os.getenv(_DATA_DIR_VAR, "").strip() or _DEFAULT_DATA_DIR
    store = TaskStore(Path(data_dir) / _TASKS_FILENAME)
    store.load()
    return store
