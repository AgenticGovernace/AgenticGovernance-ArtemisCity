"""Tests for fail-closed Authstructure verification and root authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import pytest

from src.auth.authstructure import (
    AuthstructureReceiptArtifact,
    AuthstructureVerifier,
)
from src.auth.config import AuthConfigurationError, load_auth_verifier
from src.auth.contracts import AuthReceiptSourceV1, AuthReceiptV1, PrincipalV1
from src.auth.verifier import (
    AuthenticationDenied,
    AuthenticationRequest,
    AuthorityContextFactory,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
RAW_AUTHORIZATION = "Bearer raw-transport-proof-do-not-retain"
RAW_BODY = b'{"proof":"raw-body-proof-do-not-retain"}'
EXPECTED_AUDIENCE = "artemis-city"
EXPECTED_SIGNER_NAMESPACE = "authstructure"
EXPECTED_RECEIPT_KEY_ID = "receipt-key:production-1"


def _canonical_bytes(projection: dict[str, object]) -> bytes:
    return json.dumps(
        projection,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _principal(
    *, expires_at: datetime, audience: str = EXPECTED_AUDIENCE
) -> PrincipalV1:
    return PrincipalV1.model_validate(
        {
            "identity": {
                "actor_issuer": "https://auth.example.test",
                "actor_subject_ref": "subject:alice",
                "agent_id": "agent:planner",
                "tenant_id": "tenant:city",
                "certificate_issuer": "issuer:city-ca",
                "certificate_serial": "serial:0123",
                "certificate_thumbprint": "thumbprint:abc123",
                "request_key_id": "request-key:1",
                "request_key_jkt": "jkt:request-key-1",
            },
            "capability": {
                "token_issuer": "https://auth.example.test",
                "audience": audience,
                "token_key_id": "capability-key:1",
                "token_jti_ref": "receipt-ref:jti-1",
                "granted_scopes": {"tasks:read", "tasks:route"},
            },
            "verified_at": NOW - timedelta(minutes=5),
            "expires_at": expires_at,
        }
    )


def _artifact(
    *,
    request_id: str = "request:1",
    authentication: Literal["authenticated", "rejected"] = "authenticated",
    audience: str = EXPECTED_AUDIENCE,
    receipt_format: str = "authstructure.receipt/2",
    signer_namespace: str = EXPECTED_SIGNER_NAMESPACE,
    receipt_key_id: str = EXPECTED_RECEIPT_KEY_ID,
    verified_at: datetime = NOW - timedelta(minutes=1),
    expires_at: datetime = NOW + timedelta(minutes=5),
    canonical_bytes: bytes | None = None,
    record_hash: str | None = None,
) -> AuthstructureReceiptArtifact:
    projection = {
        "proof_ref": "proof:verified-1",
        "receipt_id": "receipt:verified-1",
        "verified": authentication == "authenticated",
    }
    expected_bytes = _canonical_bytes(projection)
    source = AuthReceiptSourceV1.model_validate(
        {
            "format": receipt_format,
            "receipt_id": "receipt:verified-1",
            "record_hash": record_hash
            or f"sha256:{hashlib.sha256(expected_bytes).hexdigest()}",
            "receipt_key_id": receipt_key_id,
            "signer_namespace": signer_namespace,
            "canonical_receipt": projection,
        }
    )
    principal = (
        _principal(expires_at=expires_at, audience=audience)
        if authentication == "authenticated"
        else None
    )
    receipt = AuthReceiptV1.model_validate(
        {
            "request_id": request_id,
            "authentication": authentication,
            "principal": principal,
            "reason_code": (
                None if authentication == "authenticated" else "authentication_rejected"
            ),
            "verified_at": verified_at,
            "source": source,
        }
    )
    return AuthstructureReceiptArtifact(
        receipt=receipt,
        canonical_receipt_bytes=canonical_bytes or expected_bytes,
    )


class _ReceiptBoundary:
    def __init__(
        self,
        artifact: AuthstructureReceiptArtifact | None = None,
        error: Exception | None = None,
    ) -> None:
        self._artifact = artifact
        self._error = error

    def verify(self, request: AuthenticationRequest) -> AuthstructureReceiptArtifact:
        del request
        if self._error is not None:
            raise self._error
        assert self._artifact is not None
        return self._artifact


@pytest.fixture
def authentication_request() -> AuthenticationRequest:
    return AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route?proof=raw-target-proof-do-not-retain",
        headers={"authorization": (RAW_AUTHORIZATION,)},
        body=RAW_BODY,
    )


def _verifier(artifact: AuthstructureReceiptArtifact) -> AuthstructureVerifier:
    return AuthstructureVerifier(
        boundary=_ReceiptBoundary(artifact),
        expected_audience=EXPECTED_AUDIENCE,
        expected_signer_namespace=EXPECTED_SIGNER_NAMESPACE,
        expected_receipt_key_id=EXPECTED_RECEIPT_KEY_ID,
        clock=lambda: NOW,
    )


def _assert_denial_is_safe(
    denied: pytest.ExceptionInfo[AuthenticationDenied], expected_code: str
) -> None:
    assert denied.value.code == expected_code
    for secret in (
        RAW_AUTHORIZATION,
        RAW_BODY.decode(),
        "raw-target-proof-do-not-retain",
    ):
        assert secret not in str(denied.value)
        assert secret not in repr(denied.value)


def test_auth_errors_replace_unregistered_codes_with_safe_defaults() -> None:
    """Caller-supplied text must never become authentication error output."""
    denied = AuthenticationDenied(RAW_AUTHORIZATION)
    configuration_error = AuthConfigurationError(RAW_AUTHORIZATION)

    assert denied.code == "authentication_rejected"
    assert configuration_error.code == "auth_verifier_unavailable"
    for error in (denied, configuration_error):
        assert RAW_AUTHORIZATION not in str(error)
        assert RAW_AUTHORIZATION not in repr(error)


def test_auth_verifier_request_repr_omits_raw_transport_proof(
    authentication_request: AuthenticationRequest,
) -> None:
    """Enabling dataclass repr must not expose transient proof material."""
    representation = repr(authentication_request)

    assert RAW_AUTHORIZATION not in representation
    assert RAW_BODY.decode() not in representation
    assert "raw-target-proof-do-not-retain" not in representation
    with pytest.raises(AttributeError):
        authentication_request.body = b"replacement"  # type: ignore[misc]


def test_auth_config_missing_production_verifier_fails_closed(monkeypatch) -> None:
    """Missing integration config cannot activate a permissive verifier."""
    for key in (
        "ARTEMIS_AUTHSTRUCTURE_URL",
        "ARTEMIS_AUTHSTRUCTURE_AUDIENCE",
        "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE",
        "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(AuthConfigurationError) as denied:
        load_auth_verifier("prod")

    assert denied.value.code == "auth_verifier_unavailable"
    assert str(denied.value) == "auth_verifier_unavailable"


def test_auth_config_complete_environment_still_fails_without_public_contract(
    monkeypatch,
) -> None:
    """Configuration alone must not speculate about an unpublished endpoint."""
    monkeypatch.setenv("ARTEMIS_AUTHSTRUCTURE_URL", "https://auth.example.test")
    monkeypatch.setenv("ARTEMIS_AUTHSTRUCTURE_AUDIENCE", EXPECTED_AUDIENCE)
    monkeypatch.setenv(
        "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE", EXPECTED_SIGNER_NAMESPACE
    )
    monkeypatch.setenv("ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID", EXPECTED_RECEIPT_KEY_ID)

    with pytest.raises(AuthConfigurationError) as denied:
        load_auth_verifier("prod")

    assert denied.value.code == "auth_verifier_unavailable"


def test_authstructure_verify_rejects_wrong_contract_version(
    authentication_request: AuthenticationRequest,
) -> None:
    """Relaxing the receipt-format literal would admit an unknown contract."""
    verifier = _verifier(_artifact(receipt_format="authstructure.receipt/3"))

    with pytest.raises(AuthenticationDenied) as denied:
        verifier.verify(authentication_request)

    _assert_denial_is_safe(denied, "unsupported_receipt_version")


@pytest.mark.parametrize(
    ("artifact", "expected_code"),
    [
        (
            _artifact(signer_namespace="another-signer"),
            "invalid_signature_metadata",
        ),
        (_artifact(receipt_key_id="another-key"), "invalid_signature_metadata"),
    ],
)
def test_authstructure_verify_rejects_malformed_signature_metadata(
    authentication_request: AuthenticationRequest,
    artifact: AuthstructureReceiptArtifact,
    expected_code: str,
) -> None:
    """Signer metadata cannot select an unconfigured namespace or key."""
    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, expected_code)


def test_authstructure_verify_rejects_noncanonical_receipt_bytes(
    authentication_request: AuthenticationRequest,
) -> None:
    """Hash-valid alternate JSON bytes must not replace canonical encoding."""
    artifact = _artifact(canonical_bytes=b'{"verified":true}')

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_canonicalization_mismatch")


def test_authstructure_verify_rejects_malformed_canonical_bytes_safely(
    authentication_request: AuthenticationRequest,
) -> None:
    """Malformed adapter output must deny instead of escaping a type error."""
    artifact = _artifact()
    malformed = AuthstructureReceiptArtifact(
        receipt=artifact.receipt,
        canonical_receipt_bytes=cast(bytes, "not-bytes"),
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(malformed).verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_canonicalization_mismatch")


def test_authstructure_verify_rejects_malformed_receipt_artifact_safely(
    authentication_request: AuthenticationRequest,
) -> None:
    """An adapter returning the wrong receipt type must fail closed."""
    malformed = AuthstructureReceiptArtifact(
        receipt=cast(AuthReceiptV1, object()),
        canonical_receipt_bytes=b"{}",
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(malformed).verify(authentication_request)

    _assert_denial_is_safe(denied, "authentication_rejected")


def test_authstructure_verify_rejects_receipt_hash_mismatch(
    authentication_request: AuthenticationRequest,
) -> None:
    """Trusting declared hashes without recomputing would admit altered receipts."""
    artifact = _artifact(record_hash=f"sha256:{'0' * 64}")

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_hash_mismatch")


def test_authstructure_verify_rejects_wrong_audience(
    authentication_request: AuthenticationRequest,
) -> None:
    """A principal issued for another service must not gain routing authority."""
    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(audience="another-service")).verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_audience_mismatch")


def test_authstructure_verify_rejects_future_receipt_time(
    authentication_request: AuthenticationRequest,
) -> None:
    """Future verification evidence must fail closed when evaluated now."""
    artifact = _artifact(verified_at=NOW + timedelta(seconds=1))

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_time_invalid")


def test_authstructure_verify_rejects_expired_principal(
    authentication_request: AuthenticationRequest,
) -> None:
    """A once-valid receipt cannot preserve authority after principal expiry."""
    artifact = _artifact(
        verified_at=NOW - timedelta(minutes=2),
        expires_at=NOW - timedelta(minutes=1),
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, "principal_expired")


def test_authstructure_verify_rejects_receipt_for_another_request(
    authentication_request: AuthenticationRequest,
) -> None:
    """A valid receipt cannot be replayed across transport requests."""
    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(request_id="request:other")).verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_request_mismatch")


def test_authstructure_verify_sanitizes_boundary_failure(
    authentication_request: AuthenticationRequest,
) -> None:
    """An adapter exception must not copy transport proof into safe errors."""
    verifier = AuthstructureVerifier(
        boundary=_ReceiptBoundary(error=RuntimeError(RAW_AUTHORIZATION)),
        expected_audience=EXPECTED_AUDIENCE,
        expected_signer_namespace=EXPECTED_SIGNER_NAMESPACE,
        expected_receipt_key_id=EXPECTED_RECEIPT_KEY_ID,
        clock=lambda: NOW,
    )

    with pytest.raises(AuthenticationDenied) as denied:
        verifier.verify(authentication_request)

    _assert_denial_is_safe(denied, "auth_verifier_unavailable")


def test_authstructure_verify_returns_verified_credential_free_receipt(
    authentication_request: AuthenticationRequest,
) -> None:
    """Changing any validation branch must prevent this valid receipt result."""
    artifact = _artifact()

    receipt = _verifier(artifact).verify(authentication_request)

    assert receipt is artifact.receipt
    serialized = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)
    assert RAW_AUTHORIZATION not in serialized
    assert RAW_BODY.decode() not in serialized


def test_auth_factory_root_constructs_requester_as_actor_without_delegation() -> None:
    """Root authority must not invent a distinct actor or a delegation grant."""
    receipt = _artifact().receipt

    authority = AuthorityContextFactory().root(receipt)

    assert authority.requester is authority.actor
    assert authority.requester.principal == receipt.principal
    assert authority.requester.auth_receipt is receipt
    assert authority.delegation is None


def test_auth_factory_root_requires_authenticated_receipt() -> None:
    """A rejected receipt must never become root authority."""
    rejected_receipt = _artifact(authentication="rejected").receipt

    with pytest.raises(AuthenticationDenied) as denied:
        AuthorityContextFactory().root(rejected_receipt)

    _assert_denial_is_safe(denied, "authentication_rejected")
