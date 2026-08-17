"""Typed, transport-neutral contracts for canonical ATP validation."""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator

from src.agents.atp.atp_models import ATPActionType, ATPMode, ATPPriority

DetectedATPFormat = Literal["hash", "bracket", "none"]
IssueSeverity = Literal["error", "warning", "suggestion"]
ValidationIssueCode = Literal[
    "no_atp_headers",
    "incomplete_atp_headers",
    "empty_content",
    "content_too_short",
    "content_too_long",
    "mode_action_mismatch",
    "target_zone_not_path_like",
    "target_zone_relative",
    "atp_headers_recommended",
    "validator_error",
    "validator_warning",
    "validator_suggestion",
]

_HEADER_MARKER = re.compile(r"(?:#\w+:|\[\[\w+\]\]:)")
_LINE_BOUNDARY = re.compile(r"[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")


def _public_enum_schema(enum_type: type[Enum]) -> dict[str, object]:
    return {
        "type": "string",
        "enum": [
            member.value
            for member in enum_type.__members__.values()
            if member.name != "UNKNOWN"
        ],
    }


CanonicalATPMode = Annotated[
    ATPMode,
    Field(strict=False),
    WithJsonSchema(_public_enum_schema(ATPMode)),
]
CanonicalATPPriority = Annotated[
    ATPPriority,
    Field(strict=False),
    WithJsonSchema(_public_enum_schema(ATPPriority)),
]
CanonicalATPActionType = Annotated[
    ATPActionType,
    Field(strict=False),
    WithJsonSchema(_public_enum_schema(ATPActionType)),
]


class ValidationModel(BaseModel):
    """Strict immutable base model for validation boundary objects."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, str_strip_whitespace=True
    )


class ATPHeaderInput(ValidationModel):
    """Canonical ATP header values accepted by the formatter.

    Content is intentionally excluded: the formatter emits only a validated
    header block so callers can attach the body through their own transport.
    """

    mode: CanonicalATPMode
    context: str = Field(min_length=1)
    action_type: CanonicalATPActionType
    priority: CanonicalATPPriority = ATPPriority.NORMAL
    target_zone: str | None = Field(default=None, min_length=1)
    special_notes: str | None = Field(default=None, min_length=1)

    @field_validator("mode")
    @classmethod
    def reject_unknown_mode(cls, value: ATPMode) -> ATPMode:
        if value is ATPMode.UNKNOWN:
            raise ValueError("Mode must be canonical")
        return value

    @field_validator("action_type")
    @classmethod
    def reject_unknown_action(cls, value: ATPActionType) -> ATPActionType:
        if value is ATPActionType.UNKNOWN:
            raise ValueError("ActionType must be canonical")
        return value

    @field_validator("priority")
    @classmethod
    def reject_unknown_priority(cls, value: ATPPriority) -> ATPPriority:
        if value is ATPPriority.UNKNOWN:
            raise ValueError("Priority must be canonical")
        return value

    @field_validator("context", "target_zone", "special_notes", mode="before")
    @classmethod
    def reject_header_injection(cls, value: object) -> object:
        if isinstance(value, str) and (
            _LINE_BOUNDARY.search(value) or _HEADER_MARKER.search(value)
        ):
            raise ValueError("ATP formatter fields must be one-line data")
        return value


class ParsedATP(ValidationModel):
    """Normalized projection returned by the canonical ATP parser."""

    mode: ATPMode = Field(strict=False)
    context: str | None = Field(default=None, min_length=1)
    priority: ATPPriority = Field(strict=False)
    action_type: ATPActionType = Field(strict=False)
    target_zone: str | None = Field(default=None, min_length=1)
    special_notes: str | None = Field(default=None, min_length=1)
    content: str
    detected_format: DetectedATPFormat
    has_atp_headers: bool
    is_complete: bool


class ValidationIssue(ValidationModel):
    """One stable, client-visible ATP validation finding."""

    code: ValidationIssueCode
    severity: IssueSeverity
    message: str = Field(min_length=1)


class ATPValidationReport(ValidationModel):
    """Complete ATP validation outcome and normalized parsed message."""

    parsed: ParsedATP
    valid: bool
    strict: bool
    issues: tuple[ValidationIssue, ...]
    summary: str = Field(min_length=1)
