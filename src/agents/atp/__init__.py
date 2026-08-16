"""Canonical Artemis Transmission Protocol exports."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .atp_context import infer_capability, resolve_task_context
    from .atp_models import ATPActionType, ATPMessage, ATPMode, ATPPriority
    from .atp_parser import ATPParser
    from .atp_validator import ATPValidator, ValidationResult

    ATPValidationResult = ValidationResult


_LAZY_EXPORTS = {
    "ATPActionType": (".atp_models", "ATPActionType"),
    "ATPMessage": (".atp_models", "ATPMessage"),
    "ATPMode": (".atp_models", "ATPMode"),
    "ATPParser": (".atp_parser", "ATPParser"),
    "ATPPriority": (".atp_models", "ATPPriority"),
    "ATPValidator": (".atp_validator", "ATPValidator"),
    "ATPValidationResult": (".atp_validator", "ValidationResult"),
    "ValidationResult": (".atp_validator", "ValidationResult"),
    "infer_capability": (".atp_context", "infer_capability"),
    "resolve_task_context": (".atp_context", "resolve_task_context"),
}

# Preserve the established public import order for star imports.
__all__ = [  # noqa: RUF022
    "ATPActionType",
    "ATPMessage",
    "ATPMode",
    "ATPParser",
    "ATPPriority",
    "ATPValidator",
    "ATPValidationResult",
    "ValidationResult",
    "infer_capability",
    "resolve_task_context",
]


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value
