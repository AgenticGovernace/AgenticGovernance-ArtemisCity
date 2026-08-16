"""Production ATP context-routing tests."""

import pytest

from src.agents.atp.atp_context import resolve_task_context
from src.routing.intent import IntentDenied

ATP_SUMMARY = """#Mode: Synthesize
#Context: Condense the release notes
#Priority: Normal
#ActionType: Summarize
#TargetZone: docs/
#SpecialNotes: Preserve decisions

Summarize the release notes for operators.
"""

ATP_INVALID_BRACKET = """[[Mode]]: not-a-mode

Reject this malformed ATP message.
"""


def test_atp_context_infers_action_domain_and_cleans_content():
    resolved = resolve_task_context(
        {"content": ATP_SUMMARY, "_capability_explicit": False}
    )

    assert resolved["required_capability"] == "text_summarization"
    assert resolved["routing_scope"] == "atp:summarize:text_summarization"
    assert resolved["atp_action_type"] == "Summarize"
    assert resolved["content"] == "Summarize the release notes for operators."
    assert resolved["atp"]["context"] == "Condense the release notes"


def test_atp_context_allows_an_explicit_capability_that_equals_the_domain():
    resolved = resolve_task_context(
        {
            "content": ATP_SUMMARY,
            "required_capability": "text_summarization",
            "_capability_explicit": True,
        }
    )

    assert resolved["required_capability"] == "text_summarization"
    assert resolved["routing_scope"] == "atp:summarize:text_summarization"


def test_non_atp_context_is_unchanged():
    source = {"content": "ordinary task", "required_capability": "web_search"}
    assert resolve_task_context(source) == source


def test_atp_context_rejects_incomplete_header_without_a_caller_strictness_flag():
    with pytest.raises(ValueError, match="Incomplete ATP headers"):
        resolve_task_context({"content": "#Mode: Build\nCreate it."})


def test_atp_context_rejects_raw_bracket_atp_with_an_invalid_value():
    with pytest.raises(IntentDenied) as denied:
        resolve_task_context({"content": ATP_INVALID_BRACKET})
    assert denied.value.code == "invalid_atp"
