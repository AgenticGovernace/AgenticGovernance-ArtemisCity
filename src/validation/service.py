"""Canonical parse, validate, and format service for ATP messages.

Transport adapters should depend on :class:`ATPValidationService` instead of
reimplementing ATP parsing or translating validator strings independently.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from src.agents.atp.atp_models import ATPMessage
from src.agents.atp.atp_parser import ATPParser
from src.agents.atp.atp_validator import ATPValidator, ValidationResult

from .models import (ATPHeaderInput, ATPValidationReport, DetectedATPFormat,
                     IssueSeverity, ParsedATP, ValidationIssue,
                     ValidationIssueCode)

_EXACT_CODES: dict[str, ValidationIssueCode] = {
    "No ATP headers found in message": "no_atp_headers",
    "Consider using ATP headers for structured communication": (
        "atp_headers_recommended"
    ),
    "Message content is empty": "empty_content",
    "TargetZone should typically be a file path or project location": (
        "target_zone_not_path_like"
    ),
    "Consider using absolute paths or home-relative paths (~/) in TargetZone": (
        "target_zone_relative"
    ),
    "Consider breaking long message into multiple ATP messages": "content_too_long",
}
_PREFIX_CODES: dict[str, ValidationIssueCode] = {
    "Incomplete ATP headers:": "incomplete_atp_headers",
    "Recommended ATP headers missing:": "incomplete_atp_headers",
    "Message content is very short (": "content_too_short",
    "Mode '": "mode_action_mismatch",
}
_FALLBACK_CODES: dict[IssueSeverity, ValidationIssueCode] = {
    "error": "validator_error",
    "warning": "validator_warning",
    "suggestion": "validator_suggestion",
}


def _detected_format(value: str | None) -> DetectedATPFormat:
    if value == "hash":
        return "hash"
    if value == "bracket":
        return "bracket"
    if value is None:
        return "none"
    raise ValueError("canonical parser returned an unsupported ATP format")


def _project_message(
    message: ATPMessage, detected_format: DetectedATPFormat
) -> ParsedATP:
    return ParsedATP(
        mode=message.mode,
        context=message.context,
        priority=message.priority,
        action_type=message.action_type,
        target_zone=message.target_zone,
        special_notes=message.special_notes,
        content=message.content,
        detected_format=detected_format,
        has_atp_headers=message.has_atp_headers,
        is_complete=message.is_complete,
    )


def _issue_code(message: str, severity: IssueSeverity) -> ValidationIssueCode:
    exact = _EXACT_CODES.get(message)
    if exact is not None:
        return exact
    for prefix, code in _PREFIX_CODES.items():
        if message.startswith(prefix):
            return code
    return _FALLBACK_CODES[severity]


def _map_issues(result: ValidationResult) -> tuple[ValidationIssue, ...]:
    groups: tuple[tuple[IssueSeverity, list[str]], ...] = (
        ("error", result.errors),
        ("warning", result.warnings),
        ("suggestion", result.suggestions),
    )
    issues: list[ValidationIssue] = []
    for severity, messages in groups:
        issues.extend(
            ValidationIssue(
                code=_issue_code(message, severity),
                severity=severity,
                message=message,
            )
            for message in messages
        )
    return tuple(issues)


def _quantity(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def _summary(result: ValidationResult) -> str:
    state = "passed" if result.is_valid else "failed"
    return (
        f"ATP validation {state}: "
        f"{_quantity(len(result.errors), 'error')}, "
        f"{_quantity(len(result.warnings), 'warning')}, "
        f"{_quantity(len(result.suggestions), 'suggestion')}"
    )


def _new_validator(strict: bool) -> ATPValidator:
    return ATPValidator(strict=strict)


class ATPValidationService:
    """Expose the single transport-neutral ATP validation boundary."""

    def __init__(
        self,
        parser: ATPParser | None = None,
        validator_factory: Callable[[bool], ATPValidator] | None = None,
    ) -> None:
        self._parser = parser if parser is not None else ATPParser()
        self._validator_factory = (
            validator_factory if validator_factory is not None else _new_validator
        )

    def parse(self, raw_input: str) -> ParsedATP:
        """Parse text into the stable normalized ATP projection.

        Args:
            raw_input: ATP-formatted or plain text to parse.

        Returns:
            The canonical parsed representation, including detected syntax.

        Raises:
            TypeError: If ``raw_input`` is not text.
            ValueError: If the underlying parser reports an unknown syntax.
        """

        if not isinstance(raw_input, str):
            raise TypeError("raw_input must be text")
        message = self._parser.parse(raw_input)
        detected = _detected_format(self._parser.detect_format(raw_input))
        return _project_message(message, detected)

    def validate(self, raw_input: str, strict: bool = True) -> ATPValidationReport:
        """Validate text and return stable issue codes with parsed content.

        Args:
            raw_input: ATP-formatted or plain text to validate.
            strict: Whether missing or incomplete ATP headers are errors.

        Returns:
            An immutable validation report suitable for transport adapters.

        Raises:
            TypeError: If the input types do not match the public contract.
        """

        if not isinstance(raw_input, str):
            raise TypeError("raw_input must be text")
        if not isinstance(strict, bool):
            raise TypeError("strict must be a bool")
        message = self._parser.parse(raw_input)
        detected = _detected_format(self._parser.detect_format(raw_input))
        result = self._validator_factory(strict).validate(message)
        return ATPValidationReport(
            parsed=_project_message(message, detected),
            valid=result.is_valid,
            strict=strict,
            issues=_map_issues(result),
            summary=_summary(result),
        )

    def format(
        self,
        header: ATPHeaderInput,
        syntax: Literal["hash", "bracket"] = "bracket",
    ) -> str:
        """Render a validated ATP header block in hash or bracket syntax.

        Args:
            header: Canonical header values. Embedded line breaks and header
                markers are rejected by the model before formatting.
            syntax: ``"hash"`` for ``#Mode:`` tags or ``"bracket"`` for
                ``[[Mode]]:`` tags.

        Returns:
            The header block followed by the ATP body separator.

        Raises:
            TypeError: If ``header`` is not an :class:`ATPHeaderInput`.
            ValueError: If ``syntax`` is unsupported.
        """

        if not isinstance(header, ATPHeaderInput):
            raise TypeError("header must be ATPHeaderInput")
        if syntax not in {"hash", "bracket"}:
            raise ValueError("syntax must be 'hash' or 'bracket'")
        tag = (
            (lambda name: f"#{name}:")
            if syntax == "hash"
            else (lambda name: f"[[{name}]]:")
        )
        values = [
            ("Mode", header.mode.value),
            ("Context", header.context),
            ("Priority", header.priority.value),
            ("ActionType", header.action_type.value),
        ]
        if header.target_zone is not None:
            values.append(("TargetZone", header.target_zone))
        if header.special_notes is not None:
            values.append(("SpecialNotes", header.special_notes))
        return "\n".join(f"{tag(name)} {value}" for name, value in values) + "\n\n---\n"
