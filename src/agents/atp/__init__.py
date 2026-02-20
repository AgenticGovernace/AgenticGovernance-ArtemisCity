"""
Minimal Artemis Transmission Protocol (ATP) models, parser, and validator.

This module provides the interfaces required by tests/test_atp.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ATPMode(str, Enum):
    BUILD = "BUILD"
    REVIEW = "REVIEW"
    ORGANIZE = "ORGANIZE"
    CAPTURE = "CAPTURE"
    SYNTHESIZE = "SYNTHESIZE"
    COMMIT = "COMMIT"
    UNKNOWN = "UNKNOWN"


class ATPPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class ATPActionType(str, Enum):
    SUMMARIZE = "SUMMARIZE"
    SCAFFOLD = "SCAFFOLD"
    EXECUTE = "EXECUTE"
    REFLECT = "REFLECT"


@dataclass
class ATPMessage:
    mode: ATPMode
    context: str
    priority: ATPPriority
    action_type: ATPActionType
    target_zone: str
    special_notes: str = ""
    content: str = ""


@dataclass
class ATPValidationResult:
    is_valid: bool
    error: Optional[str] = None


class ATPParser:
    """Parse ATP formatted text into an ATPMessage."""

    def parse(self, text: str) -> Optional[ATPMessage]:
        if not text or not text.strip():
            return ATPMessage(
                mode=ATPMode.UNKNOWN,
                context="",
                priority=ATPPriority.NORMAL,
                action_type=ATPActionType.EXECUTE,
                target_zone="",
                special_notes="",
                content="",
            )

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        fields = {}
        for line in lines:
            if not line.startswith("#"):
                # If it doesn't look like ATP, return None
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip("#").strip().lower()] = value.strip()

        if not fields:
            return None

        def _map_enum(enum_cls, value, default):
            if not value:
                return default
            value = value.strip().upper()
            return enum_cls.__members__.get(value, default)

        return ATPMessage(
            mode=_map_enum(ATPMode, fields.get("mode"), ATPMode.UNKNOWN),
            context=fields.get("context", ""),
            priority=_map_enum(ATPPriority, fields.get("priority"), ATPPriority.NORMAL),
            action_type=_map_enum(
                ATPActionType, fields.get("actiontype"), ATPActionType.EXECUTE
            ),
            target_zone=fields.get("targetzone", ""),
            special_notes=fields.get("specialnotes", ""),
            content=text.strip(),
        )


class ATPValidator:
    """Basic validator for ATP messages."""

    def validate(self, message: ATPMessage) -> ATPValidationResult:
        if message is None:
            return ATPValidationResult(is_valid=False, error="Message is None")
        if not message.context:
            return ATPValidationResult(is_valid=False, error="Context is required")
        if not message.content:
            return ATPValidationResult(is_valid=False, error="Content is required")
        return ATPValidationResult(is_valid=True)


__all__ = [
    "ATPActionType",
    "ATPMessage",
    "ATPMode",
    "ATPParser",
    "ATPPriority",
    "ATPValidator",
    "ATPValidationResult",
]
