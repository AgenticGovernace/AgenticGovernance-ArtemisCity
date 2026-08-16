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
