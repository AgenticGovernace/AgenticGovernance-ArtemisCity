"""Tests for authoritative ATP and typed-adapter intent resolution."""

from pathlib import Path

import pytest

from src.routing.contracts import RequestedConstraintsV1, TaskIntentV1
from src.routing.intent import IntentDenied, IntentResolver
from src.routing.policy import IntentPolicy

ATP_REVIEW_SUMMARIZE = """#Mode: Review
#Context: Summarize the reviewed notes
#ActionType: Summarize
#TargetZone: docs/

Summarize the reviewed notes for operators.
"""

ATP_COMMIT_REFLECT = """#Mode: Commit
#Context: Record the reviewed decision
#ActionType: Reflect
#TargetZone: docs/

Record the reviewed decision for operators.
"""

ATP_INVALID_HASH = """#Mode: not-a-mode

Execute the trusted adapter request.
"""

ATP_INVALID_BRACKET = """[[Mode]]: not-a-mode

Execute the trusted adapter request.
"""


@pytest.fixture
def resolver() -> IntentResolver:
    policy_path = (
        Path(__file__).resolve().parents[2] / "config/routing/intent-policy.v1.yaml"
    )
    return IntentResolver(IntentPolicy.load(policy_path))


def execute_chat_intent() -> TaskIntentV1:
    return TaskIntentV1(
        mode="Build",
        action_type="Execute",
        context="Execute the trusted adapter request",
        target_zone="src/",
        source="typed-adapter",
    )


def test_review_summarize_cannot_expand_to_memory_write(resolver):
    with pytest.raises(IntentDenied) as denied:
        resolver.resolve(
            content=ATP_REVIEW_SUMMARIZE,
            typed_intent=None,
            requested=RequestedConstraintsV1(capability="memory:write"),
        )
    assert denied.value.code == "capability_domain_conflict"


def test_atp_presence_always_uses_strict_validation(resolver):
    with pytest.raises(IntentDenied) as denied:
        resolver.resolve(
            content=ATP_COMMIT_REFLECT,
            typed_intent=None,
            requested=RequestedConstraintsV1(),
        )
    assert denied.value.code == "invalid_atp"


def test_typed_adapter_is_rejected_when_atp_headers_are_present(resolver):
    with pytest.raises(IntentDenied) as denied:
        resolver.resolve(
            content=ATP_REVIEW_SUMMARIZE,
            typed_intent=execute_chat_intent(),
            requested=RequestedConstraintsV1(),
        )
    assert denied.value.code == "ambiguous_intent_source"


@pytest.mark.parametrize("content", [ATP_INVALID_HASH, ATP_INVALID_BRACKET])
def test_invalid_raw_atp_syntax_cannot_fall_through_to_a_typed_adapter(
    resolver, content
):
    with pytest.raises(IntentDenied) as denied:
        resolver.resolve(
            content=content,
            typed_intent=execute_chat_intent(),
            requested=RequestedConstraintsV1(),
        )
    assert denied.value.code == "ambiguous_intent_source"


@pytest.mark.parametrize("content", [ATP_INVALID_HASH, ATP_INVALID_BRACKET])
def test_invalid_raw_atp_syntax_without_adapter_is_invalid_atp(resolver, content):
    with pytest.raises(IntentDenied) as denied:
        resolver.resolve(
            content=content,
            typed_intent=None,
            requested=RequestedConstraintsV1(),
        )
    assert denied.value.code == "invalid_atp"


@pytest.mark.parametrize(
    "modified_policy",
    [
        ("artemis.intent-policy/1", "artemis.intent-policy/999"),
        (
            "Review:\n    Summarize: [text_summarization]",
            "Review:\n    Summarize: [memory:write]",
        ),
        ("fallback:\n", "unreviewed: true\nfallback:\n"),
        ("  Capture:\n    Summarize: [text_summarization]\n", ""),
        (
            "    - [Build, Execute]\n",
            "    - [Build, Execute]\n    - [Build, Execute]\n",
        ),
    ],
)
def test_policy_loader_rejects_any_unreviewed_v1_mutation(tmp_path, modified_policy):
    policy_path = (
        Path(__file__).resolve().parents[2] / "config/routing/intent-policy.v1.yaml"
    )
    original, replacement = modified_policy
    candidate = tmp_path / "intent-policy.v1.yaml"
    candidate.write_text(
        policy_path.read_text(encoding="utf-8").replace(original, replacement),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        IntentPolicy.load(candidate)
