"""Contract tests for the strict Artemis Routing Kernel envelope and results."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.auth.contracts import AuthorityContextV1
from src.routing.contracts import (
    AuthorizedRouteRequestV1,
    ContinuationV1,
    DelegationContextV1,
    KernelEventV1,
    OutcomeV1,
    RequestedConstraintsV1,
    ResolvedIntentV1,
    RoutingDecisionV1,
    TaskEnvelopeV1,
    TaskIntentV1,
    TaskSubmissionV1,
)

_SHA256 = "a" * 64


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def authority_data(now: datetime) -> AuthorityContextV1:
    principal = {
        "identity": {
            "actor_issuer": "https://auth.example.test",
            "actor_subject_ref": "subject:alice",
            "agent_id": "agent:planner",
            "tenant_id": "tenant:city",
            "certificate_issuer": "issuer:city-ca",
            "certificate_serial": "serial:0123",
            "certificate_thumbprint": "thumbprint:abc123",
            "request_key_id": "key:request-1",
            "request_key_jkt": "jkt:request-1",
        },
        "capability": {
            "token_issuer": "https://auth.example.test",
            "audience": "artemis-routing",
            "token_key_id": "key:capability-1",
            "token_jti_ref": "receipt-ref:jti-1",
            "granted_scopes": {"tasks:route"},
        },
        "verified_at": now,
        "expires_at": datetime(2026, 8, 16, 12, 5, tzinfo=UTC),
    }
    receipt = {
        "request_id": "request:root-1",
        "authentication": "authenticated",
        "principal": principal,
        "reason_code": None,
        "verified_at": now,
        "source": {
            "format": "authstructure.receipt/2",
            "receipt_id": "receipt:root-1",
            "record_hash": "sha256:receipt-1",
            "receipt_key_id": "key:receipt-1",
            "signer_namespace": "authstructure",
            "canonical_receipt": {"verified": True},
        },
    }
    party = {"principal": principal, "auth_receipt": receipt}
    return AuthorityContextV1(requester=party, actor=party, delegation=None)


@pytest.fixture
def valid_submission(now: datetime) -> dict[str, object]:
    return {
        "version": "artemis.task-submission/1",
        "task_id": "task:root-1",
        "generation": 0,
        "input_sha256": _SHA256,
        "ingress": "http",
        "content": "Route this task.",
        "intent": {
            "mode": "execute",
            "action_type": "research",
            "context": "contract test",
            "target_zone": "public",
            "source": "caller-atp",
        },
        "requested_constraints": {"capability": "research", "agent": None},
        "provenance_parent_id": None,
        "submission_idempotency_key": "submission:root-1",
        "attempt_idempotency_key": "attempt:root-1",
        "created_at": now,
    }


@pytest.fixture
def valid_envelope(
    authority_data: AuthorityContextV1, valid_submission: dict[str, object]
) -> dict[str, object]:
    return {
        **valid_submission,
        "version": "artemis.task/1",
        "authority": authority_data,
        "delegation": {
            "grant_id": None,
            "grant_hash": None,
            "root_task_id": "task:root-1",
            "parent_task_id": None,
            "parent_outcome_id": None,
            "depth": 0,
        },
        "continuation": {
            "sequence": 0,
            "child_result_set_sha256": None,
            "prior_outcome_id": None,
        },
    }


@pytest.fixture
def valid_decision() -> RoutingDecisionV1:
    return RoutingDecisionV1(
        decision_id="decision:root-1",
        task_id="task:root-1",
        generation=0,
        continuation_sequence=0,
        resolved_capability="research",
        selected_agent_id="agent:researcher",
        fallback_used=False,
        reason_code="selected",
        provenance_id="prov:decision-1",
    )


@pytest.fixture
def valid_outcome(
    now: datetime, valid_decision: RoutingDecisionV1
) -> dict[str, object]:
    return {
        "version": "artemis.outcome/1",
        "outcome_id": "outcome:root-1",
        "attempt_id": "attempt:root-1",
        "task_id": "task:root-1",
        "generation": 0,
        "continuation_sequence": 0,
        "child_result_set_sha256": None,
        "status": "success",
        "classification": "success",
        "retryable": False,
        "content_sha256": _SHA256,
        "artifact_sha256": None,
        "agent_id": "agent:researcher",
        "routing_decision": valid_decision,
        "requester_principal_ref": "subject:alice",
        "requester_auth_receipt_id": "receipt:root-1",
        "requester_auth_receipt_hash": _SHA256,
        "actor_principal_ref": "subject:alice",
        "actor_auth_receipt_id": "receipt:root-1",
        "actor_auth_receipt_hash": _SHA256,
        "delegation_grant_id": None,
        "delegation_grant_hash": None,
        "provenance_parent_id": None,
        "result_provenance_id": "prov:result-1",
        "created_at": now,
        "learning_eligible": True,
    }


def test_transport_submission_rejects_authority_alias(
    valid_submission: dict[str, object],
) -> None:
    """Removing the trusted boundary must make a caller authority constructible."""
    valid_submission["authority"] = {"principal": "caller-created"}

    with pytest.raises(ValidationError, match="authority"):
        TaskSubmissionV1(**valid_submission)


@pytest.mark.parametrize(
    "field", ["principal", "auth_receipt", "delegation", "delegation_grant"]
)
def test_transport_submission_rejects_trusted_authority_construction(
    valid_submission: dict[str, object], field: str
) -> None:
    """Removing an ingress rejection would let callers mint trusted authority."""
    valid_submission[field] = {"caller": "untrusted"}

    with pytest.raises(ValidationError, match=field):
        TaskSubmissionV1(**valid_submission)


@pytest.mark.parametrize("field", ["privateKey", "bearerToken"])
def test_transport_payload_rejects_nested_normalized_credential_aliases(
    valid_submission: dict[str, object], field: str
) -> None:
    """Removing recursive alias checks would let nested payloads carry secrets."""
    intent = dict(valid_submission["intent"])
    intent[field] = "credential-material"
    valid_submission["intent"] = intent

    with pytest.raises(ValidationError, match=f"credential material.*{field}"):
        TaskSubmissionV1(**valid_submission)


def test_task_payload_rejects_raw_bearer_and_private_key_material(
    valid_envelope: dict[str, object], valid_submission: dict[str, object]
) -> None:
    """Removing value checks would let unmistakable credentials enter payload text."""
    valid_submission["content"] = (
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"
    )
    with pytest.raises(ValidationError, match="Bearer"):
        TaskSubmissionV1(**valid_submission)

    intent = dict(valid_envelope["intent"])
    intent["context"] = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    valid_envelope["intent"] = intent
    with pytest.raises(ValidationError, match="private key"):
        TaskEnvelopeV1(**valid_envelope)


def test_task_payload_allows_benign_bearer_prose(
    valid_submission: dict[str, object],
) -> None:
    """A Bearer word followed by ordinary prose is not credential material."""
    valid_submission["content"] = "Bearer internationalization improves global UX."

    assert TaskSubmissionV1(**valid_submission).content == valid_submission["content"]


def test_task_payload_allows_sentence_ending_bearer_prose(
    valid_submission: dict[str, object],
) -> None:
    """Sentence punctuation after ordinary Bearer prose is not token punctuation."""
    valid_submission["content"] = "Bearer internationalization."

    assert TaskSubmissionV1(**valid_submission).content == valid_submission["content"]


def test_transport_submission_rejects_trusted_adapter_intent_source(
    valid_submission: dict[str, object],
) -> None:
    """Removing the ingress source check lets callers claim a trusted adapter."""
    intent = dict(valid_submission["intent"])
    intent["source"] = "typed-adapter"
    valid_submission["intent"] = intent

    with pytest.raises(ValidationError, match="typed-adapter"):
        TaskSubmissionV1(**valid_submission)


def test_trusted_envelope_allows_typed_adapter_intent_source(
    valid_envelope: dict[str, object],
) -> None:
    """Trusted adapters must retain their explicit source after ingress validation."""
    intent = dict(valid_envelope["intent"])
    intent["source"] = "typed-adapter"
    valid_envelope["intent"] = intent

    assert TaskEnvelopeV1(**valid_envelope).intent.source == "typed-adapter"


@pytest.mark.parametrize("field", ["input_sha256", "content_sha256"])
def test_sha256_identity_requires_a_lowercase_64_hex_digest(field: str) -> None:
    """Removing digest validation would admit malformed durable identities."""
    values = {"input_sha256": _SHA256, "content_sha256": _SHA256}
    values[field] = "sha256:not-a-digest"

    if field == "input_sha256":
        with pytest.raises(ValidationError, match="SHA-256"):
            TaskSubmissionV1(
                version="artemis.task-submission/1",
                task_id="task:root-1",
                generation=0,
                input_sha256=values["input_sha256"],
                ingress="http",
                content="Route this task.",
                intent=TaskIntentV1(
                    mode="execute",
                    action_type="research",
                    context="contract test",
                    target_zone="public",
                    source="caller-atp",
                ),
                requested_constraints=RequestedConstraintsV1(
                    capability="research", agent=None
                ),
                provenance_parent_id=None,
                submission_idempotency_key="submission:root-1",
                attempt_idempotency_key="attempt:root-1",
                created_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
            )
    else:
        with pytest.raises(ValidationError, match="SHA-256"):
            OutcomeV1(
                version="artemis.outcome/1",
                outcome_id="outcome:root-1",
                attempt_id="attempt:root-1",
                task_id="task:root-1",
                generation=0,
                continuation_sequence=0,
                child_result_set_sha256=None,
                status="success",
                classification="success",
                retryable=False,
                content_sha256=values["content_sha256"],
                artifact_sha256=None,
                agent_id="agent:researcher",
                routing_decision={
                    "decision_id": "decision:root-1",
                    "task_id": "task:root-1",
                    "generation": 0,
                    "continuation_sequence": 0,
                    "resolved_capability": "research",
                    "selected_agent_id": "agent:researcher",
                    "fallback_used": False,
                    "reason_code": "selected",
                    "provenance_id": "prov:decision-1",
                },
                requester_principal_ref="subject:alice",
                requester_auth_receipt_id="receipt:root-1",
                requester_auth_receipt_hash=_SHA256,
                actor_principal_ref="subject:alice",
                actor_auth_receipt_id="receipt:root-1",
                actor_auth_receipt_hash=_SHA256,
                delegation_grant_id=None,
                delegation_grant_hash=None,
                provenance_parent_id=None,
                result_provenance_id="prov:result-1",
                created_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
                learning_eligible=True,
            )


def test_root_envelope_requires_zero_continuation(
    valid_envelope: dict[str, object],
) -> None:
    """Removing root continuation validation would admit an orphan continuation."""
    valid_envelope["continuation"] = {
        "sequence": 1,
        "child_result_set_sha256": None,
        "prior_outcome_id": None,
    }

    with pytest.raises(ValidationError, match="root continuation"):
        TaskEnvelopeV1(**valid_envelope)


def test_continuation_requires_linked_result_identity() -> None:
    """Removing linked identity checks would create an untraceable continuation."""
    with pytest.raises(ValidationError, match="continuation"):
        ContinuationV1(
            sequence=1,
            child_result_set_sha256=None,
            prior_outcome_id="outcome:prior-1",
        )


def test_delegation_hashes_require_sha256_identities(
    valid_outcome: dict[str, object],
) -> None:
    """Removing grant hash validation would accept an unverifiable delegation."""
    with pytest.raises(ValidationError, match="SHA-256"):
        DelegationContextV1(
            grant_id="grant:child-1",
            grant_hash="not-a-digest",
            root_task_id="task:root-1",
            parent_task_id="task:parent-1",
            parent_outcome_id="outcome:parent-1",
            depth=1,
        )

    valid_outcome["delegation_grant_id"] = "grant:child-1"
    valid_outcome["delegation_grant_hash"] = "not-a-digest"
    with pytest.raises(ValidationError, match="SHA-256"):
        OutcomeV1(**valid_outcome)


def test_outcome_rejects_unknown_status(valid_outcome: dict[str, object]) -> None:
    """Widening the result status accepts a non-canonical durable outcome."""
    valid_outcome["status"] = "done"

    with pytest.raises(ValidationError, match="status"):
        OutcomeV1(**valid_outcome)


def test_outcome_requires_routing_decision(valid_outcome: dict[str, object]) -> None:
    """Removing the required decision makes durable outcomes unexplainable."""
    valid_outcome["routing_decision"] = None

    with pytest.raises(ValidationError, match="routing_decision"):
        OutcomeV1(**valid_outcome)


@pytest.mark.parametrize(
    "continuation_sequence, child_result_set_sha256, prior_outcome_id",
    [
        (0, _SHA256, None),
        (0, None, "outcome:prior-1"),
        (1, None, None),
        (1, _SHA256, None),
        (1, None, "outcome:prior-1"),
    ],
)
def test_outcome_requires_complete_root_or_child_continuation_identity(
    valid_outcome: dict[str, object],
    continuation_sequence: int,
    child_result_set_sha256: str | None,
    prior_outcome_id: str | None,
) -> None:
    """Removing continuation checks creates outcomes that cannot be replayed."""
    valid_outcome.update(
        {
            "continuation_sequence": continuation_sequence,
            "child_result_set_sha256": child_result_set_sha256,
            "prior_outcome_id": prior_outcome_id,
        }
    )

    with pytest.raises(ValidationError, match="continuation"):
        OutcomeV1(**valid_outcome)


@pytest.mark.parametrize(
    ("classification", "result_kind"),
    [
        ("success", "planning"),
        ("success", "checkpoint"),
        ("graph_control", "graph_control"),
    ],
)
def test_control_outcomes_are_never_learning_eligible(
    valid_outcome: dict[str, object], classification: str, result_kind: str
) -> None:
    """Removing the policy guard lets scheduler control results affect learning."""
    valid_outcome["classification"] = classification
    valid_outcome["result_kind"] = result_kind
    valid_outcome["learning_eligible"] = True

    with pytest.raises(ValidationError, match="learning_eligible"):
        OutcomeV1(**valid_outcome)


def test_models_are_strict_frozen_and_reject_naive_timestamps(
    now: datetime, valid_submission: dict[str, object]
) -> None:
    """Dropping shared model strictness admits unknown fields and mutable time data."""
    submission = TaskSubmissionV1(**valid_submission)

    with pytest.raises(ValidationError, match="timezone-aware"):
        TaskSubmissionV1(**{**valid_submission, "created_at": now.replace(tzinfo=None)})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        TaskIntentV1(
            mode="execute",
            action_type="research",
            context="contract test",
            target_zone="public",
            source="caller-atp",
            unknown="rejected",
        )
    with pytest.raises(ValidationError):
        submission.task_id = "task:mutated"  # type: ignore[misc]


def test_transport_rejects_string_to_integer_coercion(
    valid_submission: dict[str, object],
) -> None:
    """Removing strict mode would turn an untyped generation into an accepted ID."""
    valid_submission["generation"] = "0"

    with pytest.raises(ValidationError, match="int_type"):
        TaskSubmissionV1(**valid_submission)


def test_authorized_request_and_events_preserve_typed_kernel_boundaries(
    now: datetime,
    valid_envelope: dict[str, object],
    valid_decision: RoutingDecisionV1,
    valid_outcome: dict[str, object],
) -> None:
    """Removing typed composition would allow uncorrelated routing or terminal events."""
    envelope = TaskEnvelopeV1(**valid_envelope)
    resolved = ResolvedIntentV1(
        mode="execute",
        action_type="research",
        context="contract test",
        target_zone="public",
        source="caller-atp",
        capability="research",
    )
    request = AuthorizedRouteRequestV1(
        envelope=envelope,
        resolved_intent=resolved,
        authority=valid_envelope["authority"],
    )
    outcome = OutcomeV1(**valid_outcome)
    event = KernelEventV1(
        event_id="event:complete-1",
        event_type="complete",
        task_id="task:root-1",
        generation=0,
        continuation_sequence=0,
        attempt_id="attempt:root-1",
        routing_decision_id=valid_decision.decision_id,
        outcome_id=outcome.outcome_id,
        provenance_id=outcome.result_provenance_id,
        created_at=now,
    )

    assert request.resolved_intent.capability == "research"
    assert event.outcome_id == "outcome:root-1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "review"),
        ("action_type", "summarize"),
        ("context", "different context"),
        ("target_zone", "restricted"),
        ("source", "typed-adapter"),
    ],
)
def test_authorized_request_requires_resolved_intent_to_match_envelope(
    valid_envelope: dict[str, object], field: str, value: str
) -> None:
    """Removing intent alignment lets authorization apply to a different task."""
    envelope = TaskEnvelopeV1(**valid_envelope)
    resolved = {
        "mode": "execute",
        "action_type": "research",
        "context": "contract test",
        "target_zone": "public",
        "source": "caller-atp",
        "capability": "research",
    }
    resolved[field] = value

    with pytest.raises(ValidationError, match="resolved intent"):
        AuthorizedRouteRequestV1(
            envelope=envelope,
            resolved_intent=ResolvedIntentV1(**resolved),
            authority=envelope.authority,
        )


def test_authorized_request_rejects_conflicting_requested_capability(
    valid_envelope: dict[str, object],
) -> None:
    """Removing constraint alignment lets a route broaden a caller constraint."""
    envelope = TaskEnvelopeV1(**valid_envelope)
    resolved = ResolvedIntentV1(
        mode="execute",
        action_type="research",
        context="contract test",
        target_zone="public",
        source="caller-atp",
        capability="different-capability",
    )

    with pytest.raises(ValidationError, match="requested capability"):
        AuthorizedRouteRequestV1(
            envelope=envelope,
            resolved_intent=resolved,
            authority=envelope.authority,
        )
