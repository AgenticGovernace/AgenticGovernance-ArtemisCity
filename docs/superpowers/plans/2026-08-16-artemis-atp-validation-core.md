# Artemis ATP Validation Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, transport-neutral, typed ATP parse/validate/format service over Artemis City's authoritative ATP parser and validator.

**Architecture:** The new `src.validation` package is a strict immutable facade over `src.agents.atp`; it does not copy Prove's parser, enums, or validator policy. It removes mutable/nondeterministic legacy fields from public results, maps validator messages to stable issue codes, and safely formats canonical headers. This plan intentionally does not register MCP tools: the later `artemis-validation` transport package must consume this core only after the canonical authenticated MCP ingress replaces the quarantined common gate.

**Tech Stack:** Python 3.11+, Pydantic 2, existing `ATPParser`, `ATPValidator`, and pytest.

**Spec:** `docs/superpowers/specs/2026-08-16-artemis-mcp-backend-servers-design.md`

## Global Constraints

- Artemis City is the source of truth. Reuse only the Prove validator's parse/validate/format intent; do not import from `/Users/pucci/projects/prove`.
- Delegate parsing to `src.agents.atp.atp_parser.ATPParser.parse()` and strict validation to `src.agents.atp.atp_validator.ATPValidator`; do not create a second ATP grammar or policy table.
- `ATPActionType` remains exactly `Summarize`, `Scaffold`, `Execute`, and `Reflect` (plus the legacy internal `Unknown` sentinel). Prove's `Synthesize` action is invalid; `ATPMode.SYNTHESIZE` remains valid.
- Public models use Pydantic `ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)` and expose no caller-supplied identity, capability, policy, provenance, or routing authority.
- Results exclude the legacy mutable `raw_input`, `timestamp`, and `metadata` fields so repeated calls over the same text are equal and no separate raw-input copy is exposed. `ParsedATP.content` intentionally preserves the canonical parser behavior, including the whole stripped input when no ATP header is present.
- The service performs no disk or network I/O, emits nothing to stdout/stderr, and imports no MCP, Prove, provenance, EXO, reflection, registry, routing, or provider module.
- Formatter values are one-line data, not header syntax: reject every Unicode line-boundary character and embedded `#Tag:` or `[[Tag]]:` markers before rendering.
- Do not modify the canonical parser, validator, or enums in this slice. Any protocol-policy change requires its own reviewed task.
- Preserve unrelated dirty-worktree changes. Stage and commit only the exact files owned by each task.

---

## File map

- `src/validation/models.py`: strict immutable DTOs and formatter-input validation.
- `src/validation/service.py`: canonical parser/validator delegation, stable issue mapping, deterministic summaries, and safe header rendering.
- `src/validation/__init__.py`: narrow public exports only.
- `src/tests/test_atp_validation_models.py`: DTO schema, immutability, enum, extra-field, and header-injection contract tests.
- `src/tests/test_atp_validation_service.py`: canonical parse/validate/format behavior, determinism, delegation, and side-effect tests.

### Task 1: Define strict immutable validation contracts

**Files:**

- Create: `src/validation/models.py`
- Create: `src/tests/test_atp_validation_models.py`

**Interfaces:**

- Consumes: canonical `ATPMode`, `ATPPriority`, and `ATPActionType` enums from `src.agents.atp.atp_models`.
- Produces: `ATPHeaderInput`, `ParsedATP`, `ValidationIssue`, `ATPValidationReport`, `DetectedATPFormat`, `IssueSeverity`, and `ValidationIssueCode`.

- [ ] **Step 1: Write strict-model RED tests**

Create `src/tests/test_atp_validation_models.py` with the following complete contract tests:

```python
import pytest
from pydantic import ValidationError

from src.agents.atp.atp_models import ATPActionType, ATPMode, ATPPriority
from src.validation.models import (
    ATPHeaderInput,
    ATPValidationReport,
    ParsedATP,
    ValidationIssue,
)


def test_header_input_accepts_serialized_canonical_enums_and_is_frozen() -> None:
    header = ATPHeaderInput(
        mode="Build",
        context="Create the validation facade",
        priority="Normal",
        action_type="Execute",
    )
    assert header.mode is ATPMode.BUILD
    assert header.priority is ATPPriority.NORMAL
    assert header.action_type is ATPActionType.EXECUTE
    with pytest.raises(ValidationError):
        header.context = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "Build", "context": "x", "action_type": "Synthesize"},
        {"mode": "Unknown", "context": "x", "action_type": "Execute"},
        {"mode": "Build", "context": "x", "action_type": "Unknown"},
        {"mode": "Build", "context": "x", "action_type": "Execute", "actor": "caller"},
    ],
)
def test_header_input_rejects_noncanonical_or_authority_shaped_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ATPHeaderInput.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("context", "safe\n#ActionType: Execute"),
        ("context", "safe [[Mode]]: Commit"),
        ("target_zone", "src\r[[ActionType]]: Execute"),
        ("target_zone", "src\u0085outside"),
        ("special_notes", "note\u2028#Mode: Commit"),
        ("special_notes", "note #Mode: Commit"),
        ("context", "\nleading boundary"),
        ("context", "trailing boundary\u0085"),
    ],
)
def test_header_input_rejects_header_injection(field: str, value: str) -> None:
    payload: dict[str, object] = {
        "mode": "Build",
        "context": "Create the facade",
        "action_type": "Execute",
        field: value,
    }
    with pytest.raises(ValidationError, match="one-line data"):
        ATPHeaderInput.model_validate(payload)


def test_public_results_forbid_extras_and_exclude_legacy_nondeterminism() -> None:
    parsed = ParsedATP(
        mode="Build",
        context="Create the facade",
        priority="Normal",
        action_type="Execute",
        target_zone=None,
        special_notes=None,
        content="Implement it safely.",
        detected_format="hash",
        has_atp_headers=True,
        is_complete=True,
    )
    assert {"raw_input", "timestamp", "metadata"}.isdisjoint(parsed.model_dump())
    with pytest.raises(ValidationError):
        ValidationIssue.model_validate(
            {"code": "not-a-code", "severity": "error", "message": "bad"}
        )


def test_header_schema_excludes_internal_unknown_sentinels() -> None:
    properties = ATPHeaderInput.model_json_schema()["properties"]
    assert properties["mode"]["enum"] == [
        member.value for member in ATPMode if member is not ATPMode.UNKNOWN
    ]
    assert properties["priority"]["enum"] == [
        member.value for member in ATPPriority if member is not ATPPriority.UNKNOWN
    ]
    assert properties["action_type"]["enum"] == [
        member.value for member in ATPActionType if member is not ATPActionType.UNKNOWN
    ]


def test_parsed_schema_and_runtime_retain_internal_unknown_sentinels() -> None:
    schema = ParsedATP.model_json_schema()
    assert "Unknown" in schema["$defs"]["ATPMode"]["enum"]
    assert "Unknown" in schema["$defs"]["ATPPriority"]["enum"]
    assert "Unknown" in schema["$defs"]["ATPActionType"]["enum"]
    parsed = ParsedATP(
        mode="Unknown",
        context=None,
        priority="Unknown",
        action_type="Unknown",
        target_zone=None,
        special_notes=None,
        content="plain content",
        detected_format="none",
        has_atp_headers=False,
        is_complete=False,
    )
    assert parsed.mode is ATPMode.UNKNOWN
    assert parsed.action_type is ATPActionType.UNKNOWN


@pytest.mark.parametrize("field", ["context", "target_zone", "special_notes"])
def test_formatter_strings_reject_whitespace_only_values(field: str) -> None:
    payload: dict[str, object] = {
        "mode": "Build",
        "context": "Create the facade",
        "action_type": "Execute",
        field: "   ",
    }
    with pytest.raises(ValidationError):
        ATPHeaderInput.model_validate(payload)


def test_issue_and_report_are_frozen_and_report_requires_a_tuple() -> None:
    issue = ValidationIssue(
        code="content_too_short",
        severity="warning",
        message="Message content is very short (4 chars)",
    )
    with pytest.raises(ValidationError):
        issue.message = "changed"  # type: ignore[misc]
    parsed = ParsedATP(
        mode="Build",
        context="Create the facade",
        priority="Normal",
        action_type="Execute",
        target_zone=None,
        special_notes=None,
        content="body",
        detected_format="hash",
        has_atp_headers=True,
        is_complete=True,
    )
    with pytest.raises(ValidationError):
        ATPValidationReport.model_validate(
            {
                "parsed": parsed,
                "valid": True,
                "strict": True,
                "issues": [issue],
                "summary": "ATP validation passed",
            }
        )
    report = ATPValidationReport(
        parsed=parsed,
        valid=True,
        strict=True,
        issues=(issue,),
        summary="ATP validation passed",
    )
    assert report.issues == (issue,)
    with pytest.raises(ValidationError):
        report.valid = False  # type: ignore[misc]
```

- [ ] **Step 2: Run the model tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -p no:cacheprovider src/tests/test_atp_validation_models.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'src.validation'`.

- [ ] **Step 3: Implement the model contracts**

Create `src/validation/models.py` with this structure and the complete literal code set:

```python
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
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, str_strip_whitespace=True
    )


class ATPHeaderInput(ValidationModel):
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
    code: ValidationIssueCode
    severity: IssueSeverity
    message: str = Field(min_length=1)


class ATPValidationReport(ValidationModel):
    parsed: ParsedATP
    valid: bool
    strict: bool
    issues: tuple[ValidationIssue, ...]
    summary: str = Field(min_length=1)
```

- [ ] **Step 4: Run and tighten model tests**

Run:

```bash
.venv/bin/python -m pytest -p no:cacheprovider src/tests/test_atp_validation_models.py -q
```

Expected: all tests pass.

Run:

```bash
.venv/bin/black --check \
  src/validation/models.py \
  src/tests/test_atp_validation_models.py
.venv/bin/ruff check --no-cache \
  src/validation/models.py \
  src/tests/test_atp_validation_models.py
.venv/bin/mypy --follow-imports=skip \
  src/validation/models.py \
  src/tests/test_atp_validation_models.py
.venv/bin/bandit -q src/validation/models.py
```

Expected: every owned Task 1 formatting, lint, typing, and security command exits zero.

- [ ] **Step 5: Commit Task 1 only**

```bash
git add src/validation/models.py src/tests/test_atp_validation_models.py
git commit -m "feat(validation): add typed ATP contracts"
```

### Task 2: Implement canonical parse, validate, and format behavior

**Files:**

- Create: `src/validation/service.py`
- Create: `src/validation/__init__.py`
- Create: `src/tests/test_atp_validation_service.py`

**Interfaces:**

- Consumes: Task 1 DTOs; `ATPParser.parse(raw_input) -> ATPMessage`; `ATPParser.detect_format(raw_input) -> str | None`; `ATPValidator(strict).validate(message) -> ValidationResult`.
- Produces: `ATPValidationService.parse(raw_input: str) -> ParsedATP`, `ATPValidationService.validate(raw_input: str, strict: bool = True) -> ATPValidationReport`, and `ATPValidationService.format(header: ATPHeaderInput, syntax: Literal["hash", "bracket"] = "bracket") -> str`.

- [ ] **Step 1: Write canonical-service RED tests**

Create `src/tests/test_atp_validation_service.py`. Cover both canonical syntaxes and explicit validator semantics:

```python
import ast
import socket
from pathlib import Path
from typing import Any, cast

import pytest

from src.agents.atp.atp_models import ATPActionType, ATPMessage, ATPMode, ATPPriority
from src.agents.atp.atp_parser import ATPParser
from src.agents.atp.atp_validator import ATPValidator, ValidationResult
from src.validation import (
    ATPHeaderInput,
    ATPValidationReport,
    ATPValidationService,
    ParsedATP,
)

HASH_MESSAGE = """#Mode: Build
#Context: Create the validation facade
#Priority: High
#ActionType: Execute
#TargetZone: src/validation

---
Implement it safely.
"""

BRACKET_MESSAGE = """[[Mode]]: Review
[[Context]]: Review the validation facade
[[Priority]]: High
[[ActionType]]: Reflect
[[TargetZone]]: src/validation
[[SpecialNotes]]: Keep the core transport neutral

---
Review the completed facade.
"""


def test_parse_projects_only_deterministic_canonical_fields() -> None:
    service = ATPValidationService()
    first = service.parse(HASH_MESSAGE)
    second = service.parse(HASH_MESSAGE)
    assert first == second
    assert first.detected_format == "hash"
    assert first.mode.value == "Build"
    assert first.action_type.value == "Execute"
    assert first.content == "Implement it safely."
    assert {"raw_input", "timestamp", "metadata"}.isdisjoint(first.model_dump())


def test_parse_bracket_message_preserves_every_canonical_field() -> None:
    parsed = ATPValidationService().parse(BRACKET_MESSAGE)
    assert parsed.detected_format == "bracket"
    assert parsed.mode is ATPMode.REVIEW
    assert parsed.context == "Review the validation facade"
    assert parsed.priority is ATPPriority.HIGH
    assert parsed.action_type is ATPActionType.REFLECT
    assert parsed.target_zone == "src/validation"
    assert parsed.special_notes == "Keep the core transport neutral"
    assert parsed.content == "Review the completed facade."
    assert parsed.has_atp_headers is True
    assert parsed.is_complete is True


@pytest.mark.parametrize(
    "raw,code",
    [
        ("plain content", "no_atp_headers"),
        ("#Mode: Build\n#Context: x\nbody", "incomplete_atp_headers"),
        (
            "#Mode: Build\n#Context: x\n#ActionType: Synthesize\nbody content",
            "incomplete_atp_headers",
        ),
        (
            "#Mode: Build\n#Context: x\n#ActionType: Summarize\nbody content",
            "mode_action_mismatch",
        ),
    ],
)
def test_strict_validation_returns_stable_blocking_codes(raw: str, code: str) -> None:
    report = ATPValidationService().validate(raw)
    assert report.valid is False
    assert code in {issue.code for issue in report.issues}


def test_non_strict_mode_action_mismatch_is_a_suggestion() -> None:
    report = ATPValidationService().validate(
        "#Mode: Build\n#Context: x\n#ActionType: Summarize\nbody content",
        strict=False,
    )
    assert report.valid is True
    assert [(item.code, item.severity) for item in report.issues] == [
        ("mode_action_mismatch", "suggestion")
    ]


def test_headerless_parse_preserves_canonical_content_without_raw_copy() -> None:
    parsed = ATPValidationService().parse("  plain content  ")
    assert parsed.content == "plain content"
    assert "raw_input" not in parsed.model_dump()


def test_empty_content_is_a_blocking_error() -> None:
    report = ATPValidationService().validate("""#Mode: Build
#Context: Create the facade
#ActionType: Execute
""")
    assert report.valid is False
    assert ("empty_content", "error") in {
        (item.code, item.severity) for item in report.issues
    }


@pytest.mark.parametrize(
    "content,expected",
    [
        ("short", ("content_too_short", "warning")),
        ("x" * 2001, ("content_too_long", "suggestion")),
    ],
)
def test_content_length_issues_preserve_canonical_severity(
    content: str, expected: tuple[str, str]
) -> None:
    raw = (
        """#Mode: Build
#Context: Create the facade
#ActionType: Execute
"""
        + content
    )
    report = ATPValidationService().validate(raw)
    assert report.valid is True
    assert expected in {(item.code, item.severity) for item in report.issues}


@pytest.mark.parametrize(
    "target_zone,expected_codes",
    [
        ("validation", {"target_zone_not_path_like", "target_zone_relative"}),
        ("src/validation", {"target_zone_relative"}),
    ],
)
def test_target_zone_suggestions_keep_stable_codes(
    target_zone: str, expected_codes: set[str]
) -> None:
    raw = f"""#Mode: Build
#Context: Create the facade
#ActionType: Execute
#TargetZone: {target_zone}
Implement it safely.
"""
    report = ATPValidationService().validate(raw)
    suggestion_codes = {
        item.code for item in report.issues if item.severity == "suggestion"
    }
    assert suggestion_codes == expected_codes


@pytest.mark.parametrize("syntax", ["hash", "bracket"])
def test_format_is_exact_and_round_trips_through_canonical_parser(syntax: str) -> None:
    service = ATPValidationService()
    header = ATPHeaderInput(
        mode="Review",
        context="Review the validation facade",
        priority="High",
        action_type="Reflect",
        target_zone="src/validation",
        special_notes="Keep the core transport neutral",
    )
    rendered = service.format(header, syntax=syntax)  # type: ignore[arg-type]
    if syntax == "hash":
        expected = """#Mode: Review
#Context: Review the validation facade
#Priority: High
#ActionType: Reflect
#TargetZone: src/validation
#SpecialNotes: Keep the core transport neutral

---
"""
    else:
        expected = """[[Mode]]: Review
[[Context]]: Review the validation facade
[[Priority]]: High
[[ActionType]]: Reflect
[[TargetZone]]: src/validation
[[SpecialNotes]]: Keep the core transport neutral

---
"""
    assert rendered == expected
    parsed = service.parse(rendered + "Review the completed facade.")
    assert parsed.mode is ATPMode.REVIEW
    assert parsed.context == "Review the validation facade"
    assert parsed.priority is ATPPriority.HIGH
    assert parsed.action_type is ATPActionType.REFLECT
    assert parsed.target_zone == "src/validation"
    assert parsed.special_notes == "Keep the core transport neutral"
    assert parsed.content == "Review the completed facade."
    assert parsed.detected_format == syntax
    assert parsed.is_complete is True


def test_validate_delegates_once_and_preserves_result_order_and_validity() -> None:
    message = ATPMessage(
        mode=ATPMode.REVIEW,
        context="Review delegation",
        priority=ATPPriority.NORMAL,
        action_type=ATPActionType.REFLECT,
        content="Review the result.",
    )
    legacy_result = ValidationResult()
    legacy_result.is_valid = True
    legacy_result.errors = ["future validator error one", "future validator error two"]
    legacy_result.warnings = ["future validator warning"]
    legacy_result.suggestions = ["future validator suggestion"]

    class ParserSpy:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def parse(self, raw_input: str) -> ATPMessage:
            self.calls.append(("parse", raw_input))
            return message

        def detect_format(self, raw_input: str) -> str:
            self.calls.append(("detect_format", raw_input))
            return "bracket"

        def parse_with_metrics(self, _raw_input: str) -> None:
            raise AssertionError("facade must not use instrumented parsing")

    parser = ParserSpy()
    validator_calls: list[tuple[str, object]] = []

    class ValidatorSpy:
        def validate(self, candidate: ATPMessage) -> ValidationResult:
            assert candidate is message
            validator_calls.append(("validate", candidate))
            return legacy_result

    def validator_factory(strict: bool) -> ATPValidator:
        validator_calls.append(("factory", strict))
        return cast(ATPValidator, ValidatorSpy())

    service = ATPValidationService(
        parser=cast(ATPParser, parser),
        validator_factory=validator_factory,
    )
    report = service.validate("raw request", strict=False)

    assert parser.calls == [
        ("parse", "raw request"),
        ("detect_format", "raw request"),
    ]
    assert validator_calls == [("factory", False), ("validate", message)]
    assert report.valid is legacy_result.is_valid
    assert isinstance(report.issues, tuple)
    assert [(item.code, item.severity, item.message) for item in report.issues] == [
        ("validator_error", "error", "future validator error one"),
        ("validator_error", "error", "future validator error two"),
        ("validator_warning", "warning", "future validator warning"),
        ("validator_suggestion", "suggestion", "future validator suggestion"),
    ]
    assert report.summary == (
        "ATP validation passed: 2 errors, 1 warning, 1 suggestion"
    )


def test_safe_type_and_syntax_failures_do_not_echo_inputs() -> None:
    service = ATPValidationService()
    with pytest.raises(TypeError, match="raw_input must be text") as error_info:
        service.parse(cast(Any, 42))
    assert "42" not in str(error_info.value)
    with pytest.raises(TypeError, match="strict must be a bool"):
        service.validate(HASH_MESSAGE, strict=cast(Any, "true"))
    header = ATPHeaderInput(
        mode="Build",
        context="Create the validation facade",
        action_type="Execute",
    )
    with pytest.raises(ValueError, match="syntax must be"):
        service.format(header, syntax=cast(Any, "xml"))
    with pytest.raises(TypeError, match="header must be ATPHeaderInput"):
        service.format(cast(Any, {"mode": "Build"}))


def test_public_result_schemas_are_structured_models() -> None:
    parsed_schema = ParsedATP.model_json_schema()
    report_schema = ATPValidationReport.model_json_schema()
    assert parsed_schema["properties"]["mode"]["$ref"].endswith("/$defs/ATPMode")
    assert report_schema["properties"]["parsed"]["$ref"].endswith("/$defs/ParsedATP")
    assert report_schema["properties"]["issues"]["type"] == "array"


def test_calls_do_not_use_disk_network_or_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("transport-neutral validation attempted I/O")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    report = ATPValidationService().validate(HASH_MESSAGE)
    assert report.valid is True
    assert capsys.readouterr() == ("", "")


def test_validation_package_imports_match_the_transport_neutral_allowlist() -> None:
    allowed = {
        "models.py": {
            (0, "__future__"),
            (0, "enum"),
            (0, "pydantic"),
            (0, "re"),
            (0, "src.agents.atp.atp_models"),
            (0, "typing"),
        },
        "service.py": {
            (0, "__future__"),
            (0, "collections.abc"),
            (0, "src.agents.atp.atp_models"),
            (0, "src.agents.atp.atp_parser"),
            (0, "src.agents.atp.atp_validator"),
            (0, "typing"),
            (1, "models"),
        },
        "__init__.py": {(1, "models"), (1, "service")},
    }
    for filename, expected_imports in allowed.items():
        tree = ast.parse(Path("src/validation", filename).read_text(encoding="utf-8"))
        actual_imports: set[tuple[int, str]] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                actual_imports.add((node.level, node.module or ""))
            elif isinstance(node, ast.Import):
                actual_imports.update((0, alias.name) for alias in node.names)
        assert actual_imports == expected_imports
```

- [ ] **Step 2: Run the service tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -p no:cacheprovider src/tests/test_atp_validation_service.py -q
```

Expected: collection fails because `src.validation.service` and the package exports do not exist.

- [ ] **Step 3: Implement deterministic projection and stable issue mapping**

Create `src/validation/service.py` around the canonical classes:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from src.agents.atp.atp_models import ATPMessage
from src.agents.atp.atp_parser import ATPParser
from src.agents.atp.atp_validator import ATPValidator, ValidationResult

from .models import (
    ATPHeaderInput,
    ATPValidationReport,
    DetectedATPFormat,
    IssueSeverity,
    ParsedATP,
    ValidationIssue,
    ValidationIssueCode,
)

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
        if not isinstance(raw_input, str):
            raise TypeError("raw_input must be text")
        message = self._parser.parse(raw_input)
        detected = _detected_format(self._parser.detect_format(raw_input))
        return _project_message(message, detected)

    def validate(self, raw_input: str, strict: bool = True) -> ATPValidationReport:
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
```

- [ ] **Step 4: Implement safe canonical formatting**

In the same service, render only values already validated by `ATPHeaderInput`:

```python
def format(
    self,
    header: ATPHeaderInput,
    syntax: Literal["hash", "bracket"] = "bracket",
) -> str:
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
```

Do not silently default unknown syntax to bracket form. Do not add content, timestamps, IDs, provenance, or authority fields.

- [ ] **Step 5: Export the narrow public surface**

Create `src/validation/__init__.py` exactly as the narrow public surface; it does not re-export `ATPParser`, `ATPValidator`, mutable `ATPMessage`, or `ValidationResult`:

```python
"""Transport-neutral Artemis ATP validation contracts and service."""

from .models import (
    ATPHeaderInput,
    ATPValidationReport,
    DetectedATPFormat,
    IssueSeverity,
    ParsedATP,
    ValidationIssue,
    ValidationIssueCode,
)
from .service import ATPValidationService

__all__ = [
    "ATPHeaderInput",
    "ATPValidationReport",
    "ATPValidationService",
    "DetectedATPFormat",
    "IssueSeverity",
    "ParsedATP",
    "ValidationIssue",
    "ValidationIssueCode",
]
```

- [ ] **Step 6: Run focused and canonical regressions**

Run:

```bash
.venv/bin/python -m pytest -p no:cacheprovider \
  src/tests/test_atp_validation_models.py \
  src/tests/test_atp_validation_service.py \
  src/tests/test_atp.py \
  src/tests/test_atp_validator.py -q
```

Expected: all new facade tests and existing canonical ATP tests pass with no baseline count loss.

Run:

```bash
.venv/bin/black --check \
  src/validation \
  src/tests/test_atp_validation_models.py \
  src/tests/test_atp_validation_service.py
.venv/bin/ruff check --no-cache \
  src/validation \
  src/tests/test_atp_validation_models.py \
  src/tests/test_atp_validation_service.py
.venv/bin/mypy --follow-imports=skip \
  src/validation \
  src/tests/test_atp_validation_models.py \
  src/tests/test_atp_validation_service.py
.venv/bin/bandit -q -r src/validation
```

Expected: all owned-file gates pass. Record unrelated broad-suite baseline failures separately; do not fix or stage them in this task.

- [ ] **Step 7: Verify import and source boundaries**

Run:

```bash
grep -RInE "(^|[[:space:]])(from|import)[[:space:]].*(prove|mcp|provenance|exo|reflection|requests|httpx|socket|subprocess)" src/validation
```

Expected: no matches. The model and service tests above additionally assert exact enum schemas, typed nested `parsed`, and array-shaped `issues` fields.

- [ ] **Step 8: Commit Task 2 only**

```bash
git add \
  src/validation/__init__.py \
  src/validation/service.py \
  src/tests/test_atp_validation_service.py
git commit -m "feat(validation): add canonical ATP service"
```

## Completion proof

The plan is complete only when both commits have independent spec and code-quality reviews, the focused plus canonical ATP test command is green, all owned-file static/security gates are green, and the final diff contains only the five planned files. Success proves a reusable validation core; it does not claim that `artemis-validation` MCP stdio/HTTP transport, authentication, ATP authority, provenance, packaging, or live-client conformance exists.
