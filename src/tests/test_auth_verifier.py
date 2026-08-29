"""Tests for fail-closed Authstructure verification and root authority."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from urllib.parse import quote

import pytest
from src.auth.authstructure import AuthstructureReceiptArtifact, AuthstructureVerifier
from src.auth.config import (
    AuthConfigurationError,
    AuthstructureConfig,
    load_auth_verifier,
)
from src.auth.contracts import AuthReceiptSourceV1, AuthReceiptV1, PrincipalV1
from src.auth.verifier import (
    AuthenticationDenied,
    AuthenticationRequest,
    AuthorityContextFactory,
)
from src.tests.fakes import FakeAuthVerifier

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
RAW_AUTHORIZATION = "Bearer raw-transport-proof-do-not-retain"
RAW_BODY = b'{"proof":"raw-body-proof-do-not-retain"}'
EXPECTED_AUDIENCE = "artemis-city"
EXPECTED_SIGNER_NAMESPACE = "authstructure"
EXPECTED_RECEIPT_KEY_ID = "receipt-key:production-1"

_ARTEMIS_CREDENTIAL_FIELD_NAMES = (
    "ANACONDA_API_KEY",
    "ANTHROPIC_API_KEY",
    "ARTEMIS_API_KEY_DEFAULT",
    "ARTEMIS_EMBEDDING_API_KEY",
    "ARTEMIS_MEMORY_DATABASE_URL",
    "ARTEMIS_MEMORY_MIGRATION_DATABASE_URL",
    "ARTEMIS_MCP_BEARER_TOKEN",
    "ARTEMIS_SUPABASE_DB_URL",
    "ARTEMIS_TEST_DATABASE_URL",
    "ARTEMIS_VECTOR_STORE_API_KEY",
    "DOCKER_PASSWORD",
    "EXO_API_KEY",
    "FASTAPI_API_KEY",
    "GF_SECURITY_ADMIN_PASSWORD",
    "GITHUB_TOKEN",
    "GRAFANA_PASSWORD",
    "HF_TOKEN",
    "HUGGINGFACE_API_KEY",
    "MCP_API_KEY",
    "OBSIDIAN_API_KEY",
    "OPENAI_API_KEY",
    "POSTGRES_PASSWORD",
    "QDRANT_API_KEY",
    "REDIS_PASSWORD",
    "SUPABASE_DB_URL",
    "VITE_FASTAPI_API_KEY",
    "VITE_MCP_API_KEY",
)

_URI_PROOF_CASES = (
    pytest.param(
        "redis://token-only-userinfo-proof@cache.example.test/0",
        "token-only-userinfo-proof",
        id="token-only-userinfo",
    ),
    pytest.param(
        "postgresql://username-only-proof:@db.example.test/artemis",
        "username-only-proof",
        id="username-only",
    ),
    pytest.param(
        "postgresql://component-username:component-password@db.example.test/artemis",
        "component-password",
        id="password",
    ),
    pytest.param(
        "postgresql://encoded%2Dusername:encoded%2Dpassword@db.example.test/artemis",
        "encoded%2Dusername:encoded%2Dpassword",
        id="raw-percent-encoded-userinfo",
    ),
    pytest.param(
        "postgresql://encoded%2Dusername:encoded%2Dpassword@db.example.test/artemis",
        "encoded-username:encoded-password",
        id="decoded-percent-encoded-userinfo",
    ),
    pytest.param(
        "postgresql://encoded%2Dusername:encoded%2Dpassword@db.example.test/artemis",
        "encoded%2Dusername",
        id="raw-percent-encoded-username",
    ),
    pytest.param(
        "postgresql://encoded%2Dusername:encoded%2Dpassword@db.example.test/artemis",
        "encoded-username",
        id="decoded-percent-encoded-username",
    ),
    pytest.param(
        "postgresql://encoded%2Dusername:encoded%2Dpassword@db.example.test/artemis",
        "encoded%2Dpassword",
        id="raw-percent-encoded-password",
    ),
    pytest.param(
        "postgresql://encoded%2Dusername:encoded%2Dpassword@db.example.test/artemis",
        "encoded-password",
        id="decoded-percent-encoded-password",
    ),
    pytest.param(
        "postgresql://full-dsn-user:full-dsn-password@db.example.test/artemis",
        "postgresql://full-dsn-user:full-dsn-password@db.example.test/artemis",
        id="complete-uri",
    ),
)

_AUTHSTRUCTURE_URL_CASES = (
    ("https://auth.example.test", True),
    ("https://auth.example.test/verify/v1", True),
    ("https://127.0.0.1:443/verify", True),
    ("http://localhost", True),
    ("http://localhost:8080/verify", True),
    ("http://127.0.0.1:8080/verify", True),
    ("HTTPS://auth.example.test/verify", False),
    ("Http://localhost/verify", False),
    ("http://LOCALHOST/verify", False),
    ("http://127.0.0.2/verify", False),
    ("https://[::1]/verify", False),
    ("https://auth.example.test:/verify", False),
    ("https://auth.example.test:0/verify", False),
    ("https://auth.example.test:65536/verify", False),
    ("https://auth.example.test:abc/verify", False),
    ("https://user:pass@auth.example.test/verify", False),
    ("https://auth.example.test/verify?tenant=city", False),
    ("https://auth.example.test/verify#fragment", False),
    ("https://bad host.example.test/verify", False),
    ("https:///missing-host", False),
    ("https://auth.example.test./verify", False),
    ("https://-auth.example.test/verify", False),
    ("https://999.999.999.999/verify", False),
    (" https://auth.example.test/verify", False),
    ("https://auth.example.test/verify ", False),
    ("https://auth.example.test:\u0661\u0662\u0663/verify", False),
)

_AUTHSTRUCTURE_IDENTIFIER_CASES = (
    ("artemis-city", True),
    ("authstructure", True),
    ("receipt-key:production-1", True),
    ("tenant/example_v1.2", True),
    ("", False),
    ("artemis city", False),
    ("-leading-separator", False),
    ("name@namespace", False),
    ("a" * 256, False),
    (" artemis-city", False),
    ("artemis-city ", False),
)


def _canonical_bytes(projection: dict[str, object]) -> bytes:
    return json.dumps(
        projection,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _principal_data(
    *,
    expires_at: datetime,
    audience: str = EXPECTED_AUDIENCE,
    identity_overrides: dict[str, object] | None = None,
    capability_overrides: dict[str, object] | None = None,
    verified_at: datetime = NOW - timedelta(minutes=5),
) -> dict[str, object]:
    identity: dict[str, object] = {
        "actor_issuer": "https://auth.example.test",
        "actor_subject_ref": "subject:alice",
        "agent_id": "agent:planner",
        "tenant_id": "tenant:city",
        "certificate_issuer": "issuer:city-ca",
        "certificate_serial": "serial:0123",
        "certificate_thumbprint": "thumbprint:abc123",
        "request_key_id": "request-key:1",
        "request_key_jkt": "jkt:request-key-1",
    }
    capability: dict[str, object] = {
        "token_issuer": "https://auth.example.test",
        "audience": audience,
        "token_key_id": "capability-key:1",
        "token_jti_ref": "receipt-ref:jti-1",
        "granted_scopes": ["tasks:read", "tasks:route"],
    }
    identity.update(identity_overrides or {})
    capability.update(capability_overrides or {})
    return {
        "version": "artemis.principal/1",
        "identity": identity,
        "capability": capability,
        "verified_at": verified_at,
        "expires_at": expires_at,
    }


def _json_principal(principal_data: dict[str, object]) -> dict[str, object]:
    identity = cast(dict[str, object], principal_data["identity"])
    capability = cast(dict[str, object], principal_data["capability"])
    return {
        "version": principal_data["version"],
        "identity": dict(identity),
        "capability": {
            **capability,
            "granted_scopes": sorted(cast(list[str], capability["granted_scopes"])),
        },
        "verified_at": cast(datetime, principal_data["verified_at"]).isoformat(),
        "expires_at": cast(datetime, principal_data["expires_at"]).isoformat(),
    }


def _signed_projection(
    *,
    request_id: str,
    authentication: Literal["authenticated", "rejected"],
    principal_data: dict[str, object] | None,
    reason_code: str | None,
    verified_at: datetime,
    receipt_format: str,
    receipt_id: str,
    receipt_key_id: str,
    signer_namespace: str,
) -> dict[str, object]:
    return {
        "version": "artemis.auth-receipt/1",
        "request_id": request_id,
        "authentication": authentication,
        "principal": _json_principal(principal_data) if principal_data else None,
        "reason_code": reason_code,
        "verified_at": verified_at.isoformat(),
        "source": {
            "format": receipt_format,
            "receipt_id": receipt_id,
            "receipt_key_id": receipt_key_id,
            "signer_namespace": signer_namespace,
        },
    }


def _artifact(
    *,
    request_id: str = "request:1",
    authentication: Literal["authenticated", "rejected"] = "authenticated",
    audience: str = EXPECTED_AUDIENCE,
    receipt_format: str = "authstructure.receipt/2",
    signer_namespace: str = EXPECTED_SIGNER_NAMESPACE,
    receipt_key_id: str = EXPECTED_RECEIPT_KEY_ID,
    receipt_id: str = "receipt:verified-1",
    verified_at: datetime = NOW - timedelta(minutes=1),
    principal_verified_at: datetime = NOW - timedelta(minutes=5),
    expires_at: datetime = NOW + timedelta(minutes=5),
    identity_overrides: dict[str, object] | None = None,
    capability_overrides: dict[str, object] | None = None,
    canonical_bytes: bytes | None = None,
    canonical_projection: dict[str, object] | None = None,
    record_hash: str | None = None,
) -> AuthstructureReceiptArtifact:
    reason_code = (
        None if authentication == "authenticated" else "authentication_rejected"
    )
    principal_data = (
        _principal_data(
            expires_at=expires_at,
            audience=audience,
            identity_overrides=identity_overrides,
            capability_overrides=capability_overrides,
            verified_at=principal_verified_at,
        )
        if authentication == "authenticated"
        else None
    )
    projection = canonical_projection or _signed_projection(
        request_id=request_id,
        authentication=authentication,
        principal_data=principal_data,
        reason_code=reason_code,
        verified_at=verified_at,
        receipt_format=receipt_format,
        receipt_id=receipt_id,
        receipt_key_id=receipt_key_id,
        signer_namespace=signer_namespace,
    )
    expected_bytes = (
        canonical_bytes if canonical_bytes is not None else _canonical_bytes(projection)
    )
    source = AuthReceiptSourceV1.model_validate(
        {
            "format": receipt_format,
            "receipt_id": receipt_id,
            "record_hash": record_hash
            or f"sha256:{hashlib.sha256(expected_bytes).hexdigest()}",
            "receipt_key_id": receipt_key_id,
            "signer_namespace": signer_namespace,
            "canonical_receipt": projection,
        }
    )
    principal = PrincipalV1.model_validate(principal_data) if principal_data else None
    receipt = AuthReceiptV1.model_validate(
        {
            "request_id": request_id,
            "authentication": authentication,
            "principal": principal,
            "reason_code": reason_code,
            "verified_at": verified_at,
            "source": source,
        }
    )
    return AuthstructureReceiptArtifact(
        receipt=receipt,
        canonical_receipt_bytes=expected_bytes,
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


def _with_receipt(
    artifact: AuthstructureReceiptArtifact, receipt: AuthReceiptV1
) -> AuthstructureReceiptArtifact:
    return AuthstructureReceiptArtifact(
        receipt=receipt,
        canonical_receipt_bytes=artifact.canonical_receipt_bytes,
    )


def _tamper_signed_field(receipt: AuthReceiptV1, field: str) -> AuthReceiptV1:
    principal = receipt.principal
    assert principal is not None

    if field == "identity":
        identity = principal.identity.model_copy(update={"agent_id": "agent:tampered"})
        return receipt.model_copy(
            update={"principal": principal.model_copy(update={"identity": identity})}
        )
    if field == "capability":
        capability = principal.capability.model_copy(
            update={"token_key_id": "capability-key:tampered"}
        )
        return receipt.model_copy(
            update={
                "principal": principal.model_copy(update={"capability": capability})
            }
        )
    if field == "scopes":
        capability = principal.capability.model_copy(
            update={"granted_scopes": frozenset({"tasks:admin"})}
        )
        return receipt.model_copy(
            update={
                "principal": principal.model_copy(update={"capability": capability})
            }
        )
    if field == "audience":
        capability = principal.capability.model_copy(
            update={"audience": "another-service"}
        )
        return receipt.model_copy(
            update={
                "principal": principal.model_copy(update={"capability": capability})
            }
        )
    if field == "request_id":
        return receipt.model_copy(update={"request_id": "request:tampered"})
    if field == "receipt_verified_at":
        return receipt.model_copy(
            update={"verified_at": receipt.verified_at - timedelta(seconds=1)}
        )
    if field == "principal_verified_at":
        return receipt.model_copy(
            update={
                "principal": principal.model_copy(
                    update={"verified_at": principal.verified_at + timedelta(seconds=1)}
                )
            }
        )
    if field == "principal_expires_at":
        return receipt.model_copy(
            update={
                "principal": principal.model_copy(
                    update={"expires_at": principal.expires_at + timedelta(minutes=1)}
                )
            }
        )
    if field.startswith("source_"):
        source_field = field.removeprefix("source_")
        replacement = {
            "format": "authstructure.receipt/tampered",
            "receipt_id": "receipt:tampered",
            "receipt_key_id": "receipt-key:tampered",
            "signer_namespace": "signer:tampered",
        }[source_field]
        return receipt.model_copy(
            update={
                "source": receipt.source.model_copy(update={source_field: replacement})
            }
        )
    raise AssertionError(f"unknown tamper field: {field}")


def _assert_denial_is_safe(
    denied: pytest.ExceptionInfo[AuthenticationDenied], expected_code: str
) -> None:
    assert denied.value.code == expected_code
    _assert_exception_graph_is_safe(denied.value)


def _exception_graph(error: BaseException) -> list[BaseException]:
    pending = [error]
    visited: set[int] = set()
    graph: list[BaseException] = []
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        graph.append(current)
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
    return graph


def _assert_exception_graph_is_safe(error: BaseException) -> None:
    graph = _exception_graph(error)
    assert graph == [error]
    for secret in (
        RAW_AUTHORIZATION,
        RAW_BODY.decode(),
        "raw-target-proof-do-not-retain",
    ):
        for linked in graph:
            assert secret not in str(linked)
            assert secret not in repr(linked)


def _nested_secret_exception() -> ValueError:
    try:
        try:
            raise RuntimeError(RAW_AUTHORIZATION)
        except RuntimeError:
            raise LookupError(RAW_BODY.decode()) from None
    except LookupError:
        try:
            raise ValueError("adapter failed")
        except ValueError as outer:
            return outer


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


def test_auth_verifier_request_defensively_freezes_headers() -> None:
    """Mutating caller-owned header storage cannot change transient proof."""
    source_headers = {
        "authorization": (RAW_AUTHORIZATION,),
        "x-proof": ("proof:original",),
    }
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers=source_headers,
        body=RAW_BODY,
    )

    source_headers["authorization"] = ("Bearer replacement",)
    source_headers["x-proof"] = ("proof:replacement",)

    assert request.headers["authorization"] == (RAW_AUTHORIZATION,)
    assert request.headers["x-proof"] == ("proof:original",)
    with pytest.raises(TypeError):
        request.headers["x-proof"] = ("proof:mutated",)  # type: ignore[index]


@pytest.mark.parametrize(
    "headers",
    [
        {1: ("value",)},
        {"authorization": RAW_AUTHORIZATION},
        {"authorization": (RAW_AUTHORIZATION, b"not-text")},
    ],
)
def test_auth_verifier_request_rejects_malformed_header_shapes_safely(
    headers: object,
) -> None:
    """Malformed nested headers cannot enter the transient request boundary."""
    with pytest.raises(ValueError) as denied:
        AuthenticationRequest(
            transport="http",
            request_id="request:1",
            method="POST",
            authority="routing.artemis.city",
            raw_target=b"/v1/route",
            headers=cast(dict[str, tuple[str, ...]], headers),
            body=RAW_BODY,
        )

    assert str(denied.value) == "invalid_authentication_request_headers"
    assert RAW_AUTHORIZATION not in repr(denied.value)
    _assert_exception_graph_is_safe(denied.value)


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
    _assert_exception_graph_is_safe(denied.value)


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
    _assert_exception_graph_is_safe(denied.value)


def _set_valid_authstructure_environment(monkeypatch) -> None:
    monkeypatch.setenv("ARTEMIS_AUTHSTRUCTURE_URL", "https://auth.example.test/verify")
    monkeypatch.setenv("ARTEMIS_AUTHSTRUCTURE_AUDIENCE", EXPECTED_AUDIENCE)
    monkeypatch.setenv(
        "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE", EXPECTED_SIGNER_NAMESPACE
    )
    monkeypatch.setenv("ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID", EXPECTED_RECEIPT_KEY_ID)


@pytest.mark.parametrize(
    "url",
    [
        "https://auth.example.test/verify",
        "http://localhost:8080/verify",
        "http://127.0.0.1:8080/verify",
    ],
)
def test_auth_config_accepts_https_and_explicit_loopback_http(
    monkeypatch, url: str
) -> None:
    """Development HTTP is limited to explicit loopback verifier endpoints."""
    _set_valid_authstructure_environment(monkeypatch)
    monkeypatch.setenv("ARTEMIS_AUTHSTRUCTURE_URL", url)

    config = AuthstructureConfig.from_environment("dev")

    assert config.url == url
    assert config.audience == "artemis-city"
    assert config.signer_namespace == "authstructure"
    assert config.receipt_key_id == "receipt-key:production-1"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ARTEMIS_AUTHSTRUCTURE_URL", "http://auth.example.test/verify"),
        ("ARTEMIS_AUTHSTRUCTURE_URL", "http://127.0.0.2/verify"),
        ("ARTEMIS_AUTHSTRUCTURE_URL", "https://user:pass@auth.example.test"),
        ("ARTEMIS_AUTHSTRUCTURE_URL", "https://auth.example.test?tenant=city"),
        ("ARTEMIS_AUTHSTRUCTURE_URL", "https://auth.example.test#fragment"),
        ("ARTEMIS_AUTHSTRUCTURE_URL", "https://bad host.example.test"),
        ("ARTEMIS_AUTHSTRUCTURE_URL", "https:///missing-host"),
        ("ARTEMIS_AUTHSTRUCTURE_URL", "https://auth.example.test:99999"),
        ("ARTEMIS_AUTHSTRUCTURE_AUDIENCE", "artemis city"),
        ("ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE", "authstructure\nother"),
        ("ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID", "receipt key"),
        ("ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID", ""),
    ],
)
def test_auth_config_rejects_blank_or_malformed_operator_values_safely(
    monkeypatch, key: str, value: str
) -> None:
    """Malformed public configuration cannot reach verifier construction."""
    _set_valid_authstructure_environment(monkeypatch)
    monkeypatch.setenv(key, value)

    with pytest.raises(AuthConfigurationError) as denied:
        AuthstructureConfig.from_environment("prod")

    assert denied.value.code == "auth_verifier_unavailable"
    assert str(denied.value) == "auth_verifier_unavailable"
    if value:
        assert value not in repr(denied.value)
    _assert_exception_graph_is_safe(denied.value)


def test_auth_config_direct_construction_cannot_bypass_validation() -> None:
    """Callers cannot bypass semantic checks by skipping the env loader."""
    with pytest.raises(AuthConfigurationError) as denied:
        AuthstructureConfig(
            url="http://auth.example.test/verify",
            audience=EXPECTED_AUDIENCE,
            signer_namespace=EXPECTED_SIGNER_NAMESPACE,
            receipt_key_id=EXPECTED_RECEIPT_KEY_ID,
        )

    assert denied.value.code == "auth_verifier_unavailable"
    _assert_exception_graph_is_safe(denied.value)


class _ExplodingURL(str):
    def __iter__(self):
        nested = _nested_secret_exception()
        raise nested


def test_auth_config_discards_nested_secret_exception_graph() -> None:
    """Configuration failures must not retain active or nested exceptions."""
    with pytest.raises(AuthConfigurationError) as denied:
        AuthstructureConfig(
            url=cast(str, _ExplodingURL("https://auth.example.test")),
            audience=EXPECTED_AUDIENCE,
            signer_namespace=EXPECTED_SIGNER_NAMESPACE,
            receipt_key_id=EXPECTED_RECEIPT_KEY_ID,
        )

    assert denied.value.code == "auth_verifier_unavailable"
    _assert_exception_graph_is_safe(denied.value)


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


@pytest.mark.parametrize(
    "canonical_bytes",
    [
        b'{"version":"artemis.auth-receipt/1","version":"duplicate"}',
        b'{"verified_at":NaN}',
        b'{"verified_at":Infinity}',
    ],
)
def test_authstructure_verify_rejects_non_strict_canonical_json(
    authentication_request: AuthenticationRequest,
    canonical_bytes: bytes,
) -> None:
    """Duplicate keys and non-finite numbers are never canonical JSON."""
    artifact = _artifact(canonical_bytes=canonical_bytes)

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, "authentication_rejected")


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


@pytest.mark.parametrize(
    "field",
    [
        "identity",
        "capability",
        "scopes",
        "audience",
        "request_id",
        "receipt_verified_at",
        "principal_verified_at",
        "principal_expires_at",
        "source_format",
        "source_receipt_id",
        "source_receipt_key_id",
        "source_signer_namespace",
    ],
)
def test_authstructure_verify_binds_every_signed_authority_field(
    authentication_request: AuthenticationRequest,
    field: str,
) -> None:
    """Changing admitted authority without signed bytes must always deny."""
    artifact = _artifact()
    tampered = _with_receipt(artifact, _tamper_signed_field(artifact.receipt, field))

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(tampered).verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_canonicalization_mismatch")
    assert denied.value.__cause__ is None


@pytest.mark.parametrize(
    "receipt_updates",
    [
        {"version": "artemis.auth-receipt/tampered"},
        {
            "authentication": "rejected",
            "principal": None,
            "reason_code": "authentication_rejected",
        },
        {"reason_code": "authentication_rejected"},
    ],
)
def test_authstructure_verify_revalidates_unchecked_receipt_copies(
    authentication_request: AuthenticationRequest,
    receipt_updates: dict[str, object],
) -> None:
    """Unchecked model copies cannot bypass receipt state validation."""
    artifact = _artifact()
    tampered = _with_receipt(
        artifact, artifact.receipt.model_copy(update=receipt_updates)
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(tampered).verify(authentication_request)

    _assert_denial_is_safe(denied, "authentication_rejected")
    assert denied.value.__cause__ is None


@pytest.mark.parametrize(
    ("identity_field", "echoed_proof"),
    [
        ("agent_id", RAW_AUTHORIZATION),
        ("actor_subject_ref", RAW_BODY.decode()),
        (
            "tenant_id",
            "/v1/route?proof=raw-target-proof-do-not-retain",
        ),
    ],
)
def test_authstructure_verify_rejects_signed_raw_request_echoes(
    authentication_request: AuthenticationRequest,
    identity_field: str,
    echoed_proof: str,
) -> None:
    """Even signed receipts cannot retain exact transient request proof."""
    artifact = _artifact(identity_overrides={identity_field: echoed_proof})

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, "authentication_rejected")
    assert echoed_proof not in str(denied.value)
    assert echoed_proof not in repr(denied.value)
    assert denied.value.__cause__ is None


@pytest.mark.parametrize(
    "header_name",
    [
        "authorization",
        "Proxy-Authorization",
        "cookie",
        "Set-Cookie",
        "password",
        "passphrase",
        "credentials",
        "clientSecret",
        "X-Api-Key",
        "apiKey",
        "apikey",
        "bearerToken",
        "accessToken",
        "refreshToken",
        "idToken",
        "X-Auth-Token",
        "sessionToken",
        "token",
        "api-token",
        "apitoken",
        "authorization-code",
        "authorizationcode",
        "access-key",
        "accesskey",
        "secret-key",
        "secretkey",
        "client-credentials",
        "clientcredentials",
        "jwt",
        "requestProof",
        "DPoP",
        "X-Request-Signature",
        "X-Client-Proof",
        "Client-Certificate",
        "certificatePem",
        "privateKey",
    ],
)
def test_authstructure_verify_rejects_exact_sensitive_header_leaves(
    header_name: str,
) -> None:
    """Normalized credential-bearing headers remain transient proof leaves."""
    proof = "credential-leaf-do-not-retain"
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={header_name: (proof,)},
        body=b"{}",
    )
    artifact = _artifact(identity_overrides={"agent_id": proof})

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(request)

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize(
    ("header_name", "header_value", "echoed_proof"),
    [
        (
            "Authorization",
            "Bearer bearer-component-do-not-retain",
            "bearer-component-do-not-retain",
        ),
        (
            "Proxy-Authorization",
            "Basic proxy-component-do-not-retain",
            "proxy-component-do-not-retain",
        ),
        (
            "Cookie",
            "session=cookie-component-do-not-retain; theme=light",
            "cookie-component-do-not-retain",
        ),
        (
            "Set-Cookie",
            "session=set-cookie-component-do-not-retain; Path=/; HttpOnly",
            "set-cookie-component-do-not-retain",
        ),
        (
            "Cookie",
            'session="quoted;cookie=component-do-not-retain"; theme=light',
            "quoted;cookie=component-do-not-retain",
        ),
        (
            "Set-Cookie",
            'session="quoted;set-cookie=component-do-not-retain"; Path=/',
            "quoted;set-cookie=component-do-not-retain",
        ),
        (
            "Cookie",
            "session=first-cookie-secret; session=second-cookie-secret",
            "first-cookie-secret",
        ),
        (
            "Cookie",
            "session=first-cookie-secret; session=second-cookie-secret",
            "second-cookie-secret",
        ),
    ],
)
def test_authstructure_verify_rejects_sensitive_header_components(
    header_name: str,
    header_value: str,
    echoed_proof: str,
) -> None:
    """Extracted bearer, proxy, and cookie values cannot enter receipts."""
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={header_name: (header_value,)},
        body=b"{}",
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": echoed_proof})).verify(
            request
        )

    _assert_denial_is_safe(denied, "authentication_rejected")
    assert echoed_proof not in str(denied.value)
    assert echoed_proof not in repr(denied.value)


def test_authstructure_verify_rejects_embedded_sensitive_header_component() -> None:
    """A long extracted bearer token remains proof inside a larger receipt leaf."""
    token = "bearer-component-do-not-retain"
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={"Authorization": (f"Bearer {token}",)},
        body=b"{}",
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(
            _artifact(identity_overrides={"agent_id": f"prefix::{token}::suffix"})
        ).verify(request)

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize(
    "header_name",
    [
        "x_access_token",
        "XAccessToken",
        "x-refresh-token",
        "XRefreshToken",
        "x_session_token",
        "XSessionToken",
        "x-bearer-token",
        "XBearerToken",
        "provider-secret",
        "ProviderSecret",
        "provider_api_token",
        "ProviderAPIToken",
        "aws-secret-access-key",
        "AWSSecretAccessKey",
        "x_api_key",
        "XApiKey",
        "XAPIKey",
        "openai-api-key",
        "OpenAIAPIKey",
        "github-token",
        "GitHubToken",
        "stripe-secret-key",
        "StripeSecretKey",
    ],
)
def test_authstructure_verify_rejects_prefixed_and_provider_proof_aliases(
    header_name: str,
) -> None:
    """Whole-name aliases normalize across separators, camel case, and acronyms."""
    proof = "provider-credential-do-not-retain"
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={header_name: (proof,)},
        body=b"{}",
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": proof})).verify(request)

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize("credential_name", _ARTEMIS_CREDENTIAL_FIELD_NAMES)
def test_authstructure_verify_rejects_repository_credential_headers(
    credential_name: str,
) -> None:
    """Every repository-declared credential header remains transient proof."""
    proof = "repository-header-credential-do-not-retain"
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={credential_name: (proof,)},
        body=b"{}",
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": proof})).verify(request)

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize("credential_name", _ARTEMIS_CREDENTIAL_FIELD_NAMES)
def test_authstructure_verify_rejects_repository_credential_query_fields(
    credential_name: str,
) -> None:
    """Every repository-declared credential query field remains transient."""
    proof = "repository-query-credential-do-not-retain"
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=f"/v1/route?{credential_name}={proof}".encode(),
        headers={},
        body=b"{}",
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": proof})).verify(request)

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize("credential_name", _ARTEMIS_CREDENTIAL_FIELD_NAMES)
def test_authstructure_verify_rejects_nested_duplicate_repository_credentials(
    credential_name: str,
) -> None:
    """Nested duplicate credential fields cannot hide their first value."""
    first_proof = "repository-json-first-credential-do-not-retain"
    second_proof = "repository-json-second-credential-do-not-retain"
    body = (
        f'{{"outer":{{"{credential_name}":"{first_proof}",'
        f'"{credential_name}":"{second_proof}"}}}}'
    ).encode()
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={},
        body=body,
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": first_proof})).verify(
            request
        )

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize(
    "credential_name",
    [
        "ARTEMIS_API_KEY_ADMIN",
        "ARTEMIS_API_KEY_OPERATOR_7",
        "artemisApiKeyServiceAccount",
    ],
)
def test_authstructure_verify_rejects_dynamic_artemis_api_key_names(
    credential_name: str,
) -> None:
    """The runtime ARTEMIS_API_KEY_<NAME> credential family is closed as proof."""
    proof = "dynamic-artemis-api-key-do-not-retain"
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={credential_name: (proof,)},
        body=b"{}",
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": proof})).verify(request)

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize(
    "metadata_name",
    [
        "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID",
        "ARTEMIS_AUTHSTRUCTURE_URL",
        "ARTEMIS_MCP_AUTH_ISSUER_URL",
        "ARTEMIS_MCP_CAPABILITIES",
        "ARTEMIS_MCP_HTTP_CLIENT_ID",
        "ARTEMIS_MCP_HTTP_SCOPES",
        "ARTEMIS_MCP_HTTP_SUBJECT",
        "ARTEMIS_MCP_PRINCIPAL_ID",
        "ARTEMIS_MCP_RESOURCE_SERVER_URL",
        "ARTEMIS_VECTOR_STORE_URL",
        "MCP_BASE_URL",
        "OBSIDIAN_VAULT_PATH",
        "OBSIDIAN_CA_CERT",
        "EXO_MODEL_URL",
        "x-request-key-id",
        "token-key-id",
        "certificate-serial",
        "certificate-thumbprint",
    ],
)
def test_authstructure_verify_preserves_repository_metadata_field_controls(
    metadata_name: str,
) -> None:
    """Repository endpoints, paths, certificates, and identifiers are not proof."""
    metadata_value = "credential-like-metadata-control"
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={metadata_name: (metadata_value,)},
        body=b"{}",
    )

    receipt = _verifier(_artifact()).verify(request)

    assert receipt.principal is not None


def _request_with_uri_ingress(
    ingress: Literal["header", "query", "nested-json"], uri: str
) -> AuthenticationRequest:
    headers: dict[str, tuple[str, ...]] = {}
    raw_target = b"/v1/route"
    body = b"{}"
    benign_url = "https://service.example.test/resource"
    if ingress == "header":
        headers = {"resource-url": (benign_url, uri)}
    elif ingress == "query":
        raw_target = (
            f"/v1/route?url={quote(benign_url, safe='')}&url={quote(uri, safe='')}"
        ).encode()
    else:
        body = (
            f'{{"outer":{{"url":{json.dumps(benign_url)},"url":{json.dumps(uri)}}}}}'
        ).encode()
    return AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=raw_target,
        headers=headers,
        body=body,
    )


@pytest.mark.parametrize("ingress", ["header", "query", "nested-json"])
@pytest.mark.parametrize(("uri", "echoed_proof"), _URI_PROOF_CASES)
def test_authstructure_verify_rejects_uri_userinfo_proof_components(
    ingress: Literal["header", "query", "nested-json"],
    uri: str,
    echoed_proof: str,
) -> None:
    """A receipt cannot echo a URI or any raw/decoded userinfo component."""
    request = _request_with_uri_ingress(ingress, uri)

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": echoed_proof})).verify(
            request
        )

    _assert_denial_is_safe(denied, "authentication_rejected")
    for secret in (uri, echoed_proof):
        assert secret not in str(denied.value)
        assert secret not in repr(denied.value)


@pytest.mark.parametrize(
    "benign_url",
    [
        "postgresql://db.example.test/artemis",
        "https://auth.example.test/verify",
    ],
)
@pytest.mark.parametrize("ingress", ["header", "query", "nested-json"])
def test_authstructure_verify_allows_urls_without_userinfo(
    ingress: Literal["header", "query", "nested-json"],
    benign_url: str,
) -> None:
    """Duplicate structured URL fields remain benign without userinfo."""
    request = _request_with_uri_ingress(ingress, benign_url)

    receipt = _verifier(_artifact(identity_overrides={"agent_id": benign_url})).verify(
        request
    )

    assert receipt.principal is not None
    assert receipt.principal.identity.agent_id == benign_url


@pytest.mark.parametrize(
    "echoed_proof",
    [
        "raw-body-proof-do-not-retain",
        "raw-target-proof-do-not-retain",
    ],
)
def test_authstructure_verify_rejects_high_information_structured_proof_leaves(
    authentication_request: AuthenticationRequest,
    echoed_proof: str,
) -> None:
    """Named JSON and query proof values cannot enter a signed receipt."""
    artifact = _artifact(identity_overrides={"agent_id": echoed_proof})

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize(
    ("raw_target", "echoed_proof"),
    [
        (b"/v1/route?apiKey=shortsecret", "shortsecret"),
        (b"/v1/route?proof=firstsecret&proof=secondsecret", "firstsecret"),
    ],
)
def test_authstructure_verify_rejects_every_sensitive_query_occurrence(
    raw_target: bytes,
    echoed_proof: str,
) -> None:
    """Short values and duplicate sensitive query names remain transient."""
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=raw_target,
        headers={},
        body=b"{}",
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": echoed_proof})).verify(
            request
        )

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize(
    ("body", "echoed_proof"),
    [
        (b'{"password":"tiny"}', "tiny"),
        (
            b'{"proof":"duplicate-first-secret","proof":"second-secret"}',
            "duplicate-first-secret",
        ),
        (
            b'{"outer":{"proof":"nested-first-secret","proof":"nested-second-secret"}}',
            "nested-first-secret",
        ),
    ],
)
def test_authstructure_verify_rejects_every_sensitive_json_occurrence(
    body: bytes,
    echoed_proof: str,
) -> None:
    """Duplicate-preserving JSON parsing protects every named proof value."""
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={},
        body=body,
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": echoed_proof})).verify(
            request
        )

    _assert_denial_is_safe(denied, "authentication_rejected")


def test_authstructure_verify_allows_benign_transport_collisions() -> None:
    """Common body, target, and metadata values are not credential proofs."""
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/",
        headers={
            "content-type": ("application/json",),
            "user-agent": ("common-client/1.0",),
            "x-request-id": ("receipt:verified-1",),
        },
        body=b"{}",
    )

    receipt = _verifier(_artifact()).verify(request)

    assert receipt.source.receipt_id == "receipt:verified-1"


def test_authstructure_verify_rejects_embedded_high_information_proof(
    authentication_request: AuthenticationRequest,
) -> None:
    """A long credential remains proof when embedded in an admitted leaf."""
    embedded = f"credential-prefix::{RAW_AUTHORIZATION}::suffix"

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_artifact(identity_overrides={"agent_id": embedded})).verify(
            authentication_request
        )

    _assert_denial_is_safe(denied, "authentication_rejected")


@pytest.mark.parametrize(
    ("metadata_name", "metadata_value"),
    [
        ("x-request-key-id", "request-key:1"),
        ("XRequestKeyId", "request-key:1"),
        ("XREQUESTKEYID", "request-key:1"),
        ("token-key-id", "capability-key:1"),
        ("token_key_id", "capability-key:1"),
        ("certificate-serial", "serial:0123"),
        ("CertificateSerial", "serial:0123"),
        ("certificate-thumbprint", "thumbprint:abc123"),
        ("certificateThumbprint", "thumbprint:abc123"),
    ],
)
def test_authstructure_verify_does_not_classify_security_metadata_as_proof(
    metadata_name: str,
    metadata_value: str,
) -> None:
    """Identifier metadata is not a credential-bearing full-name alias."""
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={metadata_name: (metadata_value,)},
        body=b"{}",
    )

    receipt = _verifier(_artifact()).verify(request)

    assert receipt.principal is not None


def test_authstructure_verify_rejects_raw_proof_added_to_canonical_output(
    authentication_request: AuthenticationRequest,
) -> None:
    """Signed canonical output cannot carry fields outside the safe projection."""
    projection = json.loads(_artifact().canonical_receipt_bytes)
    projection["transport_echo"] = RAW_AUTHORIZATION
    artifact = _artifact(canonical_projection=projection)

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_canonicalization_mismatch")
    assert denied.value.__cause__ is None


def test_authstructure_artifact_repr_omits_receipt_and_canonical_bytes() -> None:
    """Debug repr must not expose a malicious signed transport echo."""
    projection = json.loads(_artifact().canonical_receipt_bytes)
    projection["transport_echo"] = RAW_AUTHORIZATION
    artifact = _artifact(canonical_projection=projection)

    representation = repr(artifact)

    assert RAW_AUTHORIZATION not in representation
    assert "transport_echo" not in representation


def test_authstructure_verify_sanitizes_parsed_secret_representation(
    monkeypatch,
) -> None:
    """A parser failure containing parsed proof structure cannot surface it."""
    parsed_secret = "parsed-cookie-secret-do-not-retain"
    artifact = _artifact()
    request = AuthenticationRequest(
        transport="http",
        request_id="request:1",
        method="POST",
        authority="routing.artemis.city",
        raw_target=b"/v1/route",
        headers={},
        body=f'{{"cookie":"{parsed_secret}"}}'.encode(),
    )
    real_json_loads = json.loads

    def reject_with_parsed_repr(*args, **kwargs):
        if args and args[0] == artifact.canonical_receipt_bytes:
            return real_json_loads(*args, **kwargs)
        raise RuntimeError(repr((("cookie", parsed_secret),)))

    monkeypatch.setattr("src.auth.authstructure.json.loads", reject_with_parsed_repr)

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(request)

    _assert_denial_is_safe(denied, "authentication_rejected")
    assert parsed_secret not in str(denied.value)
    assert parsed_secret not in repr(denied.value)


class _ExplodingPrincipal:
    @property
    def capability(self):
        raise _nested_secret_exception()


def test_authstructure_verify_sanitizes_nested_artifact_failure(
    authentication_request: AuthenticationRequest,
) -> None:
    """Unexpected nested artifact failures cannot escape admission processing."""
    artifact = _artifact()
    malformed_receipt = artifact.receipt.model_copy(
        update={"principal": cast(PrincipalV1, _ExplodingPrincipal())}
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_with_receipt(artifact, malformed_receipt)).verify(
            authentication_request
        )

    _assert_denial_is_safe(denied, "authentication_rejected")
    assert denied.value.__cause__ is None


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


def test_authstructure_verify_rejects_principal_verified_after_receipt(
    authentication_request: AuthenticationRequest,
) -> None:
    """A receipt cannot predate the principal verification it attests to."""
    artifact = _artifact(
        verified_at=NOW - timedelta(minutes=2),
        principal_verified_at=NOW - timedelta(minutes=1),
    )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(artifact).verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_time_invalid")


@pytest.mark.parametrize(
    "clock",
    [
        lambda: NOW.replace(tzinfo=None),
        lambda: (_ for _ in ()).throw(_nested_secret_exception()),
    ],
)
def test_authstructure_verify_sanitizes_unusable_clock(
    authentication_request: AuthenticationRequest,
    clock: Callable[[], datetime],
) -> None:
    """Naive and failed clocks must produce only a safe admission denial."""
    verifier = AuthstructureVerifier(
        boundary=_ReceiptBoundary(_artifact()),
        expected_audience=EXPECTED_AUDIENCE,
        expected_signer_namespace=EXPECTED_SIGNER_NAMESPACE,
        expected_receipt_key_id=EXPECTED_RECEIPT_KEY_ID,
        clock=clock,
    )

    with pytest.raises(AuthenticationDenied) as denied:
        verifier.verify(authentication_request)

    _assert_denial_is_safe(denied, "receipt_time_invalid")
    assert denied.value.__cause__ is None


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("receipt", NOW.replace(tzinfo=None)),
        ("principal", (NOW - timedelta(minutes=5)).replace(tzinfo=None)),
    ],
)
def test_authstructure_verify_revalidates_timestamp_awareness(
    authentication_request: AuthenticationRequest,
    field: str,
    replacement: datetime,
) -> None:
    """Unchecked naive receipt or principal timestamps must fail closed."""
    artifact = _artifact()
    receipt = artifact.receipt
    if field == "receipt":
        malformed = receipt.model_copy(update={"verified_at": replacement})
    else:
        assert receipt.principal is not None
        malformed = receipt.model_copy(
            update={
                "principal": receipt.principal.model_copy(
                    update={"verified_at": replacement}
                )
            }
        )

    with pytest.raises(AuthenticationDenied) as denied:
        _verifier(_with_receipt(artifact, malformed)).verify(authentication_request)

    _assert_denial_is_safe(denied, "authentication_rejected")
    assert denied.value.__cause__ is None


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
        boundary=_ReceiptBoundary(error=_nested_secret_exception()),
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

    assert receipt == artifact.receipt
    assert receipt is not artifact.receipt
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


def test_fake_auth_verifier_returns_or_denies_without_retaining_request(
    authentication_request: AuthenticationRequest,
) -> None:
    """The test fake must model success/denial without storing raw proof."""
    receipt = _artifact().receipt
    accepting = FakeAuthVerifier(receipt=receipt)
    denying = FakeAuthVerifier(denial_code="principal_expired")

    assert accepting.verify(authentication_request) is receipt
    with pytest.raises(AuthenticationDenied) as denied:
        denying.verify(authentication_request)

    _assert_denial_is_safe(denied, "principal_expired")
    assert denied.value.__cause__ is None
    assert all(
        value is not authentication_request for value in vars(accepting).values()
    )


_AUTHSTRUCTURE_TEMPLATE = """ARTEMIS_AUTHSTRUCTURE_URL=
ARTEMIS_AUTHSTRUCTURE_AUDIENCE=artemis-city
ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE=
ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID=
"""

_SETUP_FIXTURE_ASSETS = (
    "setup_secrets.sh",
    "scripts/environment_config.py",
    "config/environment-contract.yaml",
    "src/utils/environments.py",
    ".env.example",
    "app/api/.env.example",
    "app/web/frontend/.env.example",
    "src/.env.example",
    "app/Artemis Agentic Memory Layer/.env.example",
    "services/mcp/artemis-memory/.env.example",
    "config/service-env/provenance.env.example",
)

_SETUP_TARGET_PAIRS = (
    (".env.example", ".env"),
    ("app/api/.env.example", "app/api/.env"),
    ("app/web/frontend/.env.example", "app/web/frontend/.env"),
    ("src/.env.example", "src/.env"),
    (
        "app/Artemis Agentic Memory Layer/.env.example",
        "app/Artemis Agentic Memory Layer/.env",
    ),
    (
        "services/mcp/artemis-memory/.env.example",
        "services/mcp/artemis-memory/.env",
    ),
    ("config/service-env/provenance.env.example", "services/prove/.env"),
)


def _authstructure_env(values: dict[str, str]) -> str:
    order = (
        "ARTEMIS_AUTHSTRUCTURE_URL",
        "ARTEMIS_AUTHSTRUCTURE_AUDIENCE",
        "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE",
        "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID",
    )
    return "".join(f"{key}={values[key]}\n" for key in order if key in values)


def _duplicated_authstructure_env(
    values: dict[str, str],
    duplicate_key: str,
    *,
    invalid_first: bool,
) -> bytes:
    invalid_value = (
        "https://operator-secret@auth.example.test/verify"
        if duplicate_key == "ARTEMIS_AUTHSTRUCTURE_URL"
        else "operator-secret malformed"
    )
    duplicate_values = (
        (invalid_value, values[duplicate_key])
        if invalid_first
        else (values[duplicate_key], invalid_value)
    )
    lines = [f"{key}={value}" for key, value in values.items() if key != duplicate_key]
    lines.extend(f"{duplicate_key}={value}" for value in duplicate_values)
    lines.extend(
        (
            "MCP_API_KEY=owned-secret-must-not-rotate",
            "FASTAPI_API_KEY=owned-secret-must-not-rotate",
            "ARTEMIS_API_KEY_DEFAULT=owned-secret-must-not-rotate:admin:read",
            "REDIS_PASSWORD=owned-secret-must-not-rotate",
            "QDRANT_API_KEY=owned-secret-must-not-rotate",
            "GRAFANA_PASSWORD=owned-secret-must-not-rotate",
        )
    )
    return ("\n".join(lines) + "\n").encode()


def _copy_setup_fixture_assets(tmp_path: Path) -> Path:
    repository_root = Path(__file__).resolve().parents[2]
    for relative in _SETUP_FIXTURE_ASSETS:
        source = repository_root / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return tmp_path / "setup_secrets.sh"


def _replace_authstructure_values(
    path: Path,
    values: dict[str, str],
    *,
    append_missing: bool,
) -> None:
    keys = tuple(_valid_setup_values())
    seen: set[str] = set()
    rendered: list[str] = []
    for line in path.read_text().splitlines():
        key = line.split("=", 1)[0]
        if key not in keys:
            rendered.append(line)
            continue
        if key in values:
            rendered.append(f"{key}={values[key]}")
            seen.add(key)
    if append_missing:
        rendered.extend(
            f"{key}={values[key]}" for key in keys if key in values and key not in seen
        )
    path.write_text("\n".join(rendered).rstrip("\n") + "\n")


def _setup_secrets_fixture(tmp_path: Path, values: dict[str, str]) -> tuple[Path, Path]:
    script, root_env, targets = _realistic_setup_fixture(
        tmp_path,
        _authstructure_env(_valid_setup_values()).encode(),
    )
    bootstrap = _run_setup(script, tmp_path, "sync")
    assert bootstrap.returncode == 0, bootstrap.stdout + bootstrap.stderr
    for target in targets:
        _replace_authstructure_values(
            target,
            values,
            append_missing=target == root_env,
        )
    return script, root_env


def _realistic_setup_fixture(
    tmp_path: Path,
    root_env_bytes: bytes | None,
) -> tuple[Path, Path, tuple[Path, ...]]:
    script = _copy_setup_fixture_assets(tmp_path)
    targets: list[Path] = []
    for _example_name, env_name in _SETUP_TARGET_PAIRS:
        target = tmp_path / env_name
        target.parent.mkdir(parents=True, exist_ok=True)
        targets.append(target)
        if env_name == ".env":
            if root_env_bytes is not None:
                target.write_bytes(root_env_bytes)
        else:
            target.write_bytes(f"SENTINEL_{env_name}=unchanged\n".encode())
    return script, tmp_path / ".env", tuple(targets)


def _valid_setup_values() -> dict[str, str]:
    return {
        "ARTEMIS_AUTHSTRUCTURE_URL": "https://auth.example.test/verify",
        "ARTEMIS_AUTHSTRUCTURE_AUDIENCE": EXPECTED_AUDIENCE,
        "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE": EXPECTED_SIGNER_NAMESPACE,
        "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID": EXPECTED_RECEIPT_KEY_ID,
    }


def _run_setup(
    script: Path,
    cwd: Path,
    mode: str,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["bash", str(script)]
    if mode == "regenerate":
        command.append("--regenerate")
    elif mode == "check":
        command.append("--check")
    runtime_environment = dict(os.environ if environment is None else environment)
    runtime_environment["ARTEMIS_PYTHON"] = sys.executable
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        input="y\n",
        check=False,
        env=runtime_environment,
    )


@pytest.mark.parametrize(
    ("changes", "expected_diagnostic"),
    [
        (
            {"ARTEMIS_AUTHSTRUCTURE_URL": None},
            "missing ARTEMIS_AUTHSTRUCTURE_URL",
        ),
        (
            {"ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE": ""},
            "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE blank",
        ),
        (
            {
                "ARTEMIS_AUTHSTRUCTURE_URL": (
                    "https://operator-secret@auth.example.test/verify"
                )
            },
            "ARTEMIS_AUTHSTRUCTURE_URL malformed",
        ),
        (
            {"ARTEMIS_AUTHSTRUCTURE_AUDIENCE": "artemis city"},
            "ARTEMIS_AUTHSTRUCTURE_AUDIENCE malformed",
        ),
        (
            {"ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID": "receipt key"},
            "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID malformed",
        ),
    ],
)
def test_setup_check_reports_missing_blank_and_malformed_authstructure_values(
    tmp_path: Path,
    changes: dict[str, str | None],
    expected_diagnostic: str,
) -> None:
    """Read-only setup checks must distinguish every invalid config state."""
    values = _valid_setup_values()
    for key, value in changes.items():
        if value is None:
            values.pop(key)
        else:
            values[key] = value
    script, _ = _setup_secrets_fixture(tmp_path, values)

    result = _run_setup(script, tmp_path, "check")
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert expected_diagnostic in output
    assert "operator-secret" not in output


def test_setup_check_accepts_valid_authstructure_configuration(
    tmp_path: Path,
) -> None:
    """A complete semantically valid operator configuration is in sync."""
    script, _ = _setup_secrets_fixture(tmp_path, _valid_setup_values())

    result = _run_setup(script, tmp_path, "check")

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("duplicate_key", tuple(_valid_setup_values()))
@pytest.mark.parametrize("invalid_first", [False, True])
def test_setup_check_rejects_duplicate_authstructure_declarations_without_values(
    tmp_path: Path,
    duplicate_key: str,
    invalid_first: bool,
) -> None:
    """Check mode reports duplicate operator keys without choosing a value."""
    values = _valid_setup_values()
    script, root_env = _setup_secrets_fixture(tmp_path, values)
    content = _duplicated_authstructure_env(
        values,
        duplicate_key,
        invalid_first=invalid_first,
    )
    root_env.write_bytes(content)

    result = _run_setup(script, tmp_path, "check")
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert root_env.read_bytes() == content
    assert f"{duplicate_key} duplicate" in output
    assert "operator-secret" not in output


@pytest.mark.parametrize("mode", ["sync", "regenerate"])
@pytest.mark.parametrize("duplicate_key", tuple(_valid_setup_values()))
@pytest.mark.parametrize("invalid_first", [False, True])
def test_setup_mutating_modes_preflight_duplicate_authstructure_declarations(
    tmp_path: Path,
    mode: str,
    duplicate_key: str,
    invalid_first: bool,
) -> None:
    """Duplicate operator keys stop before every prompt, rotation, and write."""
    values = _valid_setup_values()
    root_env_bytes = _duplicated_authstructure_env(
        values,
        duplicate_key,
        invalid_first=invalid_first,
    )
    script, _, targets = _realistic_setup_fixture(tmp_path, root_env_bytes)
    before = {target: target.read_bytes() for target in targets}
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    openssl_marker = tmp_path / "openssl-called"
    fake_openssl = binary_dir / "openssl"
    fake_openssl.write_text(
        '#!/usr/bin/env bash\nprintf called > "$ARTEMIS_TEST_OPENSSL_MARKER"\n'
    )
    fake_openssl.chmod(0o700)
    environment = dict(os.environ)
    environment["PATH"] = f"{binary_dir}:{environment['PATH']}"
    environment["ARTEMIS_TEST_OPENSSL_MARKER"] = str(openssl_marker)

    result = _run_setup(script, tmp_path, mode, environment=environment)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert all(target.read_bytes() == content for target, content in before.items())
    assert not openssl_marker.exists()
    assert f"{duplicate_key} duplicate" in output
    assert "operator action required" in output
    assert "Create from its .env.example?" not in output
    assert "Setup complete." not in output
    assert "operator-secret" not in output


def test_setup_sync_and_regenerate_preserve_authstructure_values(
    tmp_path: Path,
) -> None:
    """Neither setup mode may invent or rotate operator Authstructure fields."""
    script, root_env = _setup_secrets_fixture(tmp_path, _valid_setup_values())
    expected = _valid_setup_values()

    for mode in ("sync", "regenerate"):
        result = _run_setup(script, tmp_path, mode)
        assert result.returncode == 0, result.stdout + result.stderr
        lines = set(root_env.read_text().splitlines())
        assert all(f"{key}={value}" in lines for key, value in expected.items())


@pytest.mark.parametrize("mode", ["sync", "regenerate"])
@pytest.mark.parametrize(
    ("changes", "expected_state"),
    [
        ({"ARTEMIS_AUTHSTRUCTURE_URL": None}, "missing"),
        ({"ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE": ""}, "blank"),
        (
            {"ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID": ("operator-secret malformed")},
            "malformed",
        ),
    ],
)
def test_setup_mutating_modes_preserve_invalid_operator_configuration(
    tmp_path: Path,
    mode: str,
    changes: dict[str, str | None],
    expected_state: str,
) -> None:
    """Sync and regenerate must stop without inventing operator values."""
    values = _valid_setup_values()
    for key, value in changes.items():
        if value is None:
            values.pop(key)
        else:
            values[key] = value
    script, root_env = _setup_secrets_fixture(tmp_path, values)
    expected = root_env.read_bytes()

    result = _run_setup(script, tmp_path, mode)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert root_env.read_bytes() == expected
    assert expected_state in output
    assert "operator action required" in output
    assert "Setup complete." not in output
    assert "operator-secret" not in output


@pytest.mark.parametrize("mode", ["sync", "regenerate"])
def test_setup_preflight_never_creates_missing_runtime_environment(
    tmp_path: Path,
    mode: str,
) -> None:
    """Authstructure preflight must precede target creation and prompting."""
    script, root_env, targets = _realistic_setup_fixture(tmp_path, None)
    existing_before = {
        target: target.read_bytes() for target in targets if target.exists()
    }

    result = _run_setup(script, tmp_path, mode)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert not root_env.exists()
    assert all(
        target.read_bytes() == content for target, content in existing_before.items()
    )
    assert "missing target" in output
    assert "operator action required" in output
    assert "Create from its .env.example?" not in output
    assert "Setup complete." not in output


@pytest.mark.parametrize("mode", ["sync", "regenerate"])
def test_setup_preflight_prevents_every_write_for_malformed_configuration(
    tmp_path: Path,
    mode: str,
) -> None:
    """Invalid operator config blocks secret rotation and all reconciliation."""
    original_secret = "owned-secret-must-not-rotate"
    root_env_bytes = (
        "ARTEMIS_AUTHSTRUCTURE_URL=https://operator-secret@auth.example.test/verify\n"
        "ARTEMIS_AUTHSTRUCTURE_AUDIENCE=artemis-city\n"
        "ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE=authstructure\n"
        "ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID=receipt-key:production-1\n"
        f"MCP_API_KEY={original_secret}\n"
        f"FASTAPI_API_KEY={original_secret}\n"
        f"ARTEMIS_API_KEY_DEFAULT={original_secret}:admin:read\n"
        f"REDIS_PASSWORD={original_secret}\n"
        f"QDRANT_API_KEY={original_secret}\n"
        f"GRAFANA_PASSWORD={original_secret}\n"
    ).encode()
    script, root_env, targets = _realistic_setup_fixture(tmp_path, root_env_bytes)
    before = {target: target.read_bytes() for target in targets}

    result = _run_setup(script, tmp_path, mode)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert all(target.read_bytes() == content for target, content in before.items())
    assert original_secret.encode() in root_env.read_bytes()
    assert "malformed" in output
    assert "operator action required" in output
    assert "operator-secret" not in output
    assert "Setup complete." not in output


@pytest.mark.parametrize(("url", "accepted"), _AUTHSTRUCTURE_URL_CASES)
def test_authstructure_url_grammar_matches_python_and_shell(
    tmp_path: Path,
    monkeypatch,
    url: str,
    accepted: bool,
) -> None:
    """Python admission and setup checks share one literal URL grammar."""
    values = _valid_setup_values()
    values["ARTEMIS_AUTHSTRUCTURE_URL"] = url
    script, _ = _setup_secrets_fixture(tmp_path, values)

    try:
        AuthstructureConfig(
            url=url,
            audience=EXPECTED_AUDIENCE,
            signer_namespace=EXPECTED_SIGNER_NAMESPACE,
            receipt_key_id=EXPECTED_RECEIPT_KEY_ID,
        )
    except AuthConfigurationError:
        constructor_accepted = False
    else:
        constructor_accepted = True

    _set_valid_authstructure_environment(monkeypatch)
    monkeypatch.setenv("ARTEMIS_AUTHSTRUCTURE_URL", url)
    try:
        AuthstructureConfig.from_environment("test")
    except AuthConfigurationError:
        environment_accepted = False
    else:
        environment_accepted = True
    shell_result = _run_setup(script, tmp_path, "check")

    assert constructor_accepted is accepted
    assert environment_accepted is accepted
    assert (shell_result.returncode == 0) is accepted


@pytest.mark.parametrize(
    ("environment_key", "config_field"),
    [
        ("ARTEMIS_AUTHSTRUCTURE_AUDIENCE", "audience"),
        ("ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE", "signer_namespace"),
        ("ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID", "receipt_key_id"),
    ],
)
@pytest.mark.parametrize(("value", "accepted"), _AUTHSTRUCTURE_IDENTIFIER_CASES)
def test_authstructure_identifier_grammar_matches_python_and_shell(
    tmp_path: Path,
    monkeypatch,
    environment_key: str,
    config_field: str,
    value: str,
    accepted: bool,
) -> None:
    """All three public identifier fields use the same constrained grammar."""
    values = _valid_setup_values()
    values[environment_key] = value
    script, _ = _setup_secrets_fixture(tmp_path, values)
    config_values = {
        "url": values["ARTEMIS_AUTHSTRUCTURE_URL"],
        "audience": values["ARTEMIS_AUTHSTRUCTURE_AUDIENCE"],
        "signer_namespace": values["ARTEMIS_AUTHSTRUCTURE_SIGNER_NAMESPACE"],
        "receipt_key_id": values["ARTEMIS_AUTHSTRUCTURE_RECEIPT_KEY_ID"],
    }
    assert config_values[config_field] == value

    try:
        AuthstructureConfig(**config_values)
    except AuthConfigurationError:
        constructor_accepted = False
    else:
        constructor_accepted = True

    _set_valid_authstructure_environment(monkeypatch)
    monkeypatch.setenv(environment_key, value)
    try:
        AuthstructureConfig.from_environment("test")
    except AuthConfigurationError:
        environment_accepted = False
    else:
        environment_accepted = True
    shell_result = _run_setup(script, tmp_path, "check")

    assert constructor_accepted is accepted
    assert environment_accepted is accepted
    assert (shell_result.returncode == 0) is accepted
