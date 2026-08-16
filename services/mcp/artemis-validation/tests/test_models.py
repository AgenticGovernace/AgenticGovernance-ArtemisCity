from __future__ import annotations

import pytest
from artemis_validation_mcp.models import (
    FormatATPInput,
    FormatATPResult,
    ParseATPInput,
    ParseATPResult,
    ValidateATPInput,
)
from pydantic import ValidationError

from src.validation import ATPHeaderInput, ATPValidationService


def test_input_models_are_flat_strict_and_forbid_extras() -> None:
    for model in (ParseATPInput, ValidateATPInput, FormatATPInput):
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False

    with pytest.raises(ValidationError):
        ParseATPInput.model_validate({"raw_input": "plain", "actor": "caller"})

    with pytest.raises(ValidationError):
        ValidateATPInput.model_validate({"raw_input": "plain", "strict": 1})


def test_format_input_advertises_only_canonical_public_enums() -> None:
    properties = FormatATPInput.model_json_schema()["properties"]

    assert properties["mode"]["enum"] == [
        "Build",
        "Review",
        "Organize",
        "Capture",
        "Synthesize",
        "Commit",
        "Reflect",
    ]
    assert properties["action_type"]["enum"] == [
        "Summarize",
        "Scaffold",
        "Execute",
        "Reflect",
    ]
    assert properties["priority"]["enum"] == [
        "Critical",
        "High",
        "Normal",
        "Low",
    ]
    assert properties["priority"]["default"] == "Normal"
    assert properties["syntax"]["enum"] == ["hash", "bracket"]
    assert properties["syntax"]["default"] == "bracket"
    assert "Unknown" not in properties["mode"]["enum"]
    assert "Synthesize" not in properties["action_type"]["enum"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("context", "safe\n#ActionType: Execute"),
        ("target_zone", "src\u2028#Mode: Build"),
        ("special_notes", "safe [[Priority]]: Critical"),
    ],
)
def test_format_input_preserves_canonical_injection_rejection(
    field: str,
    value: str,
) -> None:
    payload = {
        "mode": "Build",
        "context": "validation",
        "action_type": "Execute",
        field: value,
    }

    with pytest.raises(ValidationError):
        FormatATPInput.model_validate(payload)


def test_result_models_are_typed_frozen_and_non_echoing_in_summary() -> None:
    service = ATPValidationService()
    parsed = service.parse("plain request body")
    parse_result = ParseATPResult.from_parsed(parsed)

    assert parse_result.parsed is parsed
    assert parse_result.summary == (
        "ATP parse completed: detected_format=none, "
        "has_atp_headers=false, is_complete=false."
    )
    assert "plain request body" not in parse_result.summary

    header = ATPHeaderInput(
        mode="Build",
        context="validation",
        action_type="Execute",
    )
    format_result = FormatATPResult(
        header=header,
        syntax="bracket",
        formatted="[[Mode]]: Build\n\n---\n",
        summary="ATP header formatted using bracket syntax.",
    )
    with pytest.raises(ValidationError, match="frozen"):
        format_result.summary = "changed"
    with pytest.raises(ValidationError):
        FormatATPResult.model_validate({**format_result.model_dump(), "summary": ""})
