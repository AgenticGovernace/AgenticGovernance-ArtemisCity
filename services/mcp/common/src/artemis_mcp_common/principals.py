"""Fail-closed principal providers for Artemis City MCP transports."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import secrets
from typing import Sequence

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from .gate import GovernanceDenied
from .models import ServicePrincipal


@dataclass(frozen=True)
class LocalPrincipalProvider:
    """Provides a stdio principal from explicitly supplied environment values."""

    principal_id: str | None
    capabilities: frozenset[str]

    @classmethod
    def from_environment(cls) -> LocalPrincipalProvider:
        """Build a provider from local transport configuration without defaults."""
        capabilities = frozenset(
            capability.strip()
            for capability in os.getenv("ARTEMIS_MCP_CAPABILITIES", "").split(",")
            if capability.strip()
        )
        return cls(
            principal_id=os.getenv("ARTEMIS_MCP_PRINCIPAL_ID"),
            capabilities=capabilities,
        )

    def current(self) -> ServicePrincipal:
        """Return the configured principal or deny an incomplete configuration."""
        if not self.principal_id or not self.capabilities:
            raise GovernanceDenied("local principal configuration is incomplete")
        return ServicePrincipal(
            principal_id=self.principal_id,
            capabilities=set(self.capabilities),
            transport="stdio",
        )


class BearerPrincipalProvider:
    """Provides an HTTP principal exclusively from MCP SDK auth context."""

    def current(self) -> ServicePrincipal:
        """Return the SDK-authenticated bearer principal or deny its absence."""
        access_token = get_access_token()
        if (
            access_token is None
            or not access_token.subject
            or not access_token.scopes
        ):
            raise GovernanceDenied("bearer principal authentication is unavailable")
        return ServicePrincipal(
            principal_id=access_token.subject,
            capabilities=set(access_token.scopes),
            transport="http",
        )


@dataclass(frozen=True, repr=False)
class StaticBearerTokenVerifier:
    """Verify one configured bearer token using constant-time comparison."""

    expected_token: str = field(repr=False)
    subject: str
    scopes: Sequence[str]
    client_id: str = "artemis-mcp"

    def __post_init__(self) -> None:
        """Reject incomplete verifier configuration before serving requests."""
        if not self.expected_token or not self.subject or not self.scopes:
            raise ValueError("static bearer verifier configuration is incomplete")

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return SDK access data for an exact match, otherwise deny anonymously."""
        if not secrets.compare_digest(token, self.expected_token):
            return None
        return AccessToken(
            token=self.expected_token,
            client_id=self.client_id,
            subject=self.subject,
            scopes=list(self.scopes),
        )
