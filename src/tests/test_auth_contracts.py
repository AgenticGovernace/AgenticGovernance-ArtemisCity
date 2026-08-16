"""Contract tests for credential-free authentication and delegated authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.auth.contracts import (AuthorityContextV1, AuthReceiptSourceV1,
                                AuthReceiptV1, DelegationReferenceV1,
                                PrincipalCapabilityV1, PrincipalV1,
                                VerifiedPartyV1)
from src.auth.delegation import DelegationGrantV1


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def principal_data(now: datetime) -> dict[str, object]:
    return {
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
            "granted_scopes": {"tasks:route", "tasks:read"},
        },
        "verified_at": now - timedelta(minutes=1),
        "expires_at": now + timedelta(minutes=5),
    }


def receipt_source() -> AuthReceiptSourceV1:
    return AuthReceiptSourceV1(
        format="authstructure.receipt/2",
        receipt_id="receipt:verified-1",
        record_hash="sha256:receipt-1",
        receipt_key_id="key:receipt-1",
        signer_namespace="authstructure",
        canonical_receipt={"proof_ref": "proof:verified-1", "verified": True},
    )


def authenticated_receipt(
    *, now: datetime, principal_data: dict[str, object]
) -> AuthReceiptV1:
    return AuthReceiptV1(
        request_id="req-1",
        authentication="authenticated",
        principal=PrincipalV1(**principal_data),
        reason_code=None,
        verified_at=now,
        source=receipt_source(),
    )


@pytest.fixture
def root_authority_data(
    now: datetime, principal_data: dict[str, object]
) -> dict[str, object]:
    principal = PrincipalV1(**principal_data)
    receipt = authenticated_receipt(now=now, principal_data=principal_data)
    party = VerifiedPartyV1(principal=principal, auth_receipt=receipt)
    return {"requester": party, "actor": party, "delegation": None}


def test_authenticated_receipt_requires_unexpired_principal(
    now: datetime, principal_data: dict[str, object]
) -> None:
    principal_data["expires_at"] = now

    with pytest.raises(ValidationError, match="expires_at"):
        authenticated_receipt(now=now, principal_data=principal_data)


def test_rejected_receipt_cannot_carry_principal(
    now: datetime, principal_data: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="rejected receipt"):
        AuthReceiptV1(
            request_id="req-1",
            authentication="rejected",
            principal=PrincipalV1(**principal_data),
            reason_code="invalid_request_proof",
            verified_at=now,
            source=receipt_source(),
        )


@pytest.mark.parametrize(
    "field",
    ["token", "api_key", "private_key", "authorization_code", "certificate_pem"],
)
def test_authority_models_reject_secret_aliases(
    field: str, root_authority_data: dict[str, object]
) -> None:
    root_authority_data[field] = "secret"

    with pytest.raises(ValidationError, match=field):
        AuthorityContextV1(**root_authority_data)


def test_receipt_projection_rejects_nested_credential_material() -> None:
    with pytest.raises(ValidationError, match="bearer_token"):
        AuthReceiptSourceV1(
            format="authstructure.receipt/2",
            receipt_id="receipt:verified-1",
            record_hash="sha256:receipt-1",
            receipt_key_id="key:receipt-1",
            signer_namespace="authstructure",
            canonical_receipt={"receipt": {"bearer_token": "do-not-store"}},
        )


def test_receipt_projection_is_recursively_immutable_after_validation() -> None:
    source = AuthReceiptSourceV1(
        format="authstructure.receipt/2",
        receipt_id="receipt:verified-1",
        record_hash="sha256:receipt-1",
        receipt_key_id="key:receipt-1",
        signer_namespace="authstructure",
        canonical_receipt={"receipt": {"proof_ref": "proof:verified-1"}},
    )

    with pytest.raises(TypeError, match="immutable"):
        source.canonical_receipt["receipt"]["private_key"] = "do-not-store"


def test_receipt_projection_rejects_dict_mutation_bypass() -> None:
    source = AuthReceiptSourceV1(
        format="authstructure.receipt/2",
        receipt_id="receipt:verified-1",
        record_hash="sha256:receipt-1",
        receipt_key_id="key:receipt-1",
        signer_namespace="authstructure",
        canonical_receipt={"proof_ref": "proof:verified-1"},
    )

    with pytest.raises(TypeError):
        dict.__setitem__(source.canonical_receipt, "private_key", "do-not-store")


@pytest.mark.parametrize("value", [b"opaque-bytes", object()])
def test_receipt_projection_rejects_non_json_values(value: object) -> None:
    with pytest.raises(ValidationError, match="JSON-safe"):
        AuthReceiptSourceV1(
            format="authstructure.receipt/2",
            receipt_id="receipt:verified-1",
            record_hash="sha256:receipt-1",
            receipt_key_id="key:receipt-1",
            signer_namespace="authstructure",
            canonical_receipt={"safe_key": value},
        )


@pytest.mark.parametrize("field", ["bearerToken", "certificatePem"])
def test_receipt_projection_rejects_normalized_nested_credential_aliases(
    field: str,
) -> None:
    with pytest.raises(ValidationError, match=field):
        AuthReceiptSourceV1(
            format="authstructure.receipt/2",
            receipt_id="receipt:verified-1",
            record_hash="sha256:receipt-1",
            receipt_key_id="key:receipt-1",
            signer_namespace="authstructure",
            canonical_receipt={"receipt": {field: "do-not-store"}},
        )


def test_principal_requires_aware_increasing_evidence_times(
    now: datetime, principal_data: dict[str, object]
) -> None:
    principal_data["verified_at"] = now.replace(tzinfo=None)

    with pytest.raises(ValidationError, match="timezone-aware"):
        PrincipalV1(**principal_data)

    principal_data["verified_at"] = now
    principal_data["expires_at"] = now
    with pytest.raises(ValidationError, match="expires_at"):
        PrincipalV1(**principal_data)


def test_capability_normalizes_nonempty_scopes() -> None:
    capability = PrincipalCapabilityV1(
        token_issuer="https://auth.example.test",
        audience="artemis-routing",
        token_key_id="key:capability-1",
        token_jti_ref="receipt-ref:jti-1",
        granted_scopes={" tasks:route ", "", "tasks:route"},
    )

    assert capability.granted_scopes == frozenset({"tasks:route"})

    with pytest.raises(ValidationError, match="verified evidence"):
        PrincipalCapabilityV1(
            token_issuer="https://auth.example.test",
            audience="artemis-routing",
            token_key_id="key:capability-1",
            token_jti_ref="receipt-ref:jti-1",
            granted_scopes={" "},
        )


def test_authenticated_receipt_requires_principal_and_no_reason_code(
    now: datetime, principal_data: dict[str, object]
) -> None:
    with pytest.raises(ValidationError, match="authenticated receipt"):
        AuthReceiptV1(
            request_id="req-1",
            authentication="authenticated",
            principal=None,
            reason_code=None,
            verified_at=now,
            source=receipt_source(),
        )

    with pytest.raises(ValidationError, match="reason_code"):
        AuthReceiptV1(
            request_id="req-1",
            authentication="authenticated",
            principal=PrincipalV1(**principal_data),
            reason_code="unexpected",
            verified_at=now,
            source=receipt_source(),
        )


def test_authority_party_requires_matching_authenticated_receipt(
    now: datetime, principal_data: dict[str, object]
) -> None:
    principal = PrincipalV1(**principal_data)
    rejected = AuthReceiptV1(
        request_id="req-rejected",
        authentication="rejected",
        principal=None,
        reason_code="invalid_request_proof",
        verified_at=now,
        source=receipt_source(),
    )

    with pytest.raises(ValidationError, match="authenticated"):
        VerifiedPartyV1(principal=principal, auth_receipt=rejected)


def test_delegation_reference_requires_id_and_hash_together() -> None:
    with pytest.raises(ValidationError, match="grant_id"):
        DelegationReferenceV1(grant_id="grant-1", grant_hash=None)


def _canonical_grant_hash(grant_data: dict[str, object]) -> str:
    payload = {key: value for key, value in grant_data.items() if key != "grant_hash"}
    canonical = json.dumps(
        payload,
        default=lambda value: (
            value.isoformat() if isinstance(value, datetime) else sorted(value)
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


@pytest.fixture
def grant_data(now: datetime) -> dict[str, object]:
    data: dict[str, object] = {
        "version": "artemis.delegation-grant/1",
        "grant_id": "grant:child-1",
        "grant_hash": "",
        "root_task_id": "task:root-1",
        "parent_task_id": "task:parent-1",
        "parent_outcome_id": "outcome:parent-1",
        "requester_principal_ref": "subject:alice",
        "requester_auth_receipt_id": "receipt:requester-1",
        "requester_auth_receipt_hash": "sha256:requester-1",
        "actor_principal_ref": "service:scheduler",
        "actor_auth_receipt_id": "receipt:actor-1",
        "actor_auth_receipt_hash": "sha256:actor-1",
        "allowed_modes": {"execute"},
        "allowed_action_types": {"research"},
        "allowed_capabilities": {"llm_chat"},
        "allowed_target_zones": {"public"},
        "depth_limit": 2,
        "budget_reservation_id": "budget:child-1",
        "issued_at": now,
        "expires_at": now + timedelta(minutes=5),
        "policy_version": "routing-policy/1",
    }
    data["grant_hash"] = _canonical_grant_hash(data)
    return data


def test_delegation_grant_verifies_canonical_hash_and_is_immutable(
    grant_data: dict[str, object],
) -> None:
    grant = DelegationGrantV1(**grant_data)

    assert grant.grant_hash == grant_data["grant_hash"]
    with pytest.raises(ValidationError, match="grant_hash"):
        DelegationGrantV1(**{**grant_data, "grant_hash": "0" * 64})
    with pytest.raises(ValidationError):
        grant.depth_limit = 3  # type: ignore[misc]
