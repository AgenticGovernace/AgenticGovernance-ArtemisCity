"""Behavioral tests for governed MCP principal and ATP authorization."""

import asyncio
from datetime import timezone

import pytest
from mcp.server.auth.provider import AccessToken
from pydantic import ValidationError

from artemis_mcp_common.gate import GovernedGate, GovernanceDenied
from artemis_mcp_common.models import AtpEnvelope, ServicePrincipal
from artemis_mcp_common.principals import (
    BearerPrincipalProvider,
    LocalPrincipalProvider,
    StaticBearerTokenVerifier,
)


def _approved_envelope() -> AtpEnvelope:
    return AtpEnvelope(
        mode="Commit",
        context="Store reviewed memory",
        action_type="Execute",
        target_zone="memory/reviewed",
        parent_provenance_id="prov-root",
    )


def test_local_principal_fails_closed_without_identity(monkeypatch):
    """Missing local identity must never create a default principal."""
    monkeypatch.delenv("ARTEMIS_MCP_PRINCIPAL_ID", raising=False)
    monkeypatch.delenv("ARTEMIS_MCP_CAPABILITIES", raising=False)

    with pytest.raises(GovernanceDenied, match="principal configuration"):
        LocalPrincipalProvider.from_environment().current()


def test_incomplete_atp_envelope_is_rejected_by_contract():
    """Authority-bearing ATP metadata must include its provenance parent."""
    with pytest.raises(ValidationError, match="parent_provenance_id"):
        AtpEnvelope(
            mode="Commit",
            context="Store reviewed memory",
            action_type="Execute",
            target_zone="memory/reviewed",
        )


def test_gate_rejects_unauthorized_capability_after_validating_atp():
    """An otherwise valid request cannot elevate a reader to memory writer."""
    principal = ServicePrincipal(
        principal_id="reader",
        capabilities={"memory:read"},
    )

    with pytest.raises(GovernanceDenied, match="memory:write"):
        GovernedGate().authorize(principal, _approved_envelope(), "memory:write")


def test_gate_rejects_unknown_atp_values_before_capability_check():
    """An invalid ATP envelope is denied even when the capability is missing."""
    principal = ServicePrincipal(
        principal_id="reader",
        capabilities={"memory:read"},
    )
    envelope = AtpEnvelope(
        mode="NotACanonicalMode",
        context="Store reviewed memory",
        action_type="Execute",
        target_zone="memory/reviewed",
        parent_provenance_id="prov-root",
    )

    with pytest.raises(GovernanceDenied, match="ATP"):
        GovernedGate().authorize(principal, envelope, "memory:write")


def test_gate_returns_timezone_aware_context_for_authorized_request():
    """An authorized request receives an auditable, UTC acceptance timestamp."""
    principal = ServicePrincipal(
        principal_id="writer",
        capabilities={"memory:write"},
    )

    context = GovernedGate().authorize(
        principal,
        _approved_envelope(),
        "memory:write",
    )

    assert context.principal == principal
    assert context.capability == "memory:write"
    assert context.accepted_at.tzinfo == timezone.utc


def test_bearer_principal_uses_sdk_auth_context(monkeypatch):
    """HTTP principals derive identity and scopes only from SDK auth context."""
    sdk_token = AccessToken(
        token="sdk-token",
        client_id="memory-client",
        subject="bearer-subject",
        scopes=["memory:read", "memory:write"],
    )
    monkeypatch.setattr(
        "artemis_mcp_common.principals.get_access_token",
        lambda: sdk_token,
    )

    principal = BearerPrincipalProvider().current()

    assert principal.principal_id == "bearer-subject"
    assert principal.capabilities == {"memory:read", "memory:write"}
    assert principal.transport == "http"


def test_bearer_principal_fails_closed_without_sdk_auth_context(monkeypatch):
    """No bearer context must never create an anonymous HTTP principal."""
    monkeypatch.setattr(
        "artemis_mcp_common.principals.get_access_token",
        lambda: None,
    )

    with pytest.raises(GovernanceDenied, match="bearer"):
        BearerPrincipalProvider().current()


def test_static_bearer_verifier_returns_none_for_wrong_token_without_leaking_it():
    """A bad bearer token is rejected without appearing in error text or reprs."""
    verifier = StaticBearerTokenVerifier(
        expected_token="configured-secret",
        subject="memory-service",
        scopes=["memory:write"],
    )
    untrusted_token = "wrong-secret"

    result = asyncio.run(verifier.verify_token(untrusted_token))

    assert result is None
    assert untrusted_token not in repr(verifier)
    assert untrusted_token not in str(result)


def test_static_bearer_verifier_returns_sdk_access_token_for_match():
    """An exact match returns the SDK token and configured identity metadata."""
    expected_token = "configured-secret"
    verifier = StaticBearerTokenVerifier(
        expected_token=expected_token,
        subject="memory-service",
        scopes=["memory:read", "memory:write"],
    )

    result = asyncio.run(verifier.verify_token(expected_token))

    assert type(result) is AccessToken
    assert result.token == expected_token
    assert result.client_id == "artemis-mcp"
    assert result.subject == "memory-service"
    assert result.scopes == ["memory:read", "memory:write"]
