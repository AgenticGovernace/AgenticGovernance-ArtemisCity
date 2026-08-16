"""Shared Artemis City utility exports."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .helpers import logger, sanitize_for_log
    from .run_logger import get_run_logger, init_run_logger


_LAZY_EXPORTS = {
    "logger": (".helpers", "logger"),
    "sanitize_for_log": (".helpers", "sanitize_for_log"),
    "get_run_logger": (".run_logger", "get_run_logger"),
    "init_run_logger": (".run_logger", "init_run_logger"),
}

# Preserve the established public import order for star imports.
__all__ = [  # noqa: RUF022
    "logger",
    "sanitize_for_log",
    "get_run_logger",
    "init_run_logger",
]


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
