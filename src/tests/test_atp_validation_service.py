import ast
import socket
from pathlib import Path
from typing import Any, cast

import pytest

from src.agents.atp.atp_models import (ATPActionType, ATPMessage, ATPMode,
                                       ATPPriority)
from src.agents.atp.atp_parser import ATPParser
from src.agents.atp.atp_validator import ATPValidator, ValidationResult
from src.validation import (ATPHeaderInput, ATPValidationReport,
                            ATPValidationService, ParsedATP)

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
    raw = """#Mode: Build
#Context: Create the facade
#ActionType: Execute
""" + content
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
