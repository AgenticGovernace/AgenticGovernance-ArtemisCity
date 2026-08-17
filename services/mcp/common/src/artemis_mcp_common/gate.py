"""Strict ATP and capability authorization for Artemis City MCP services."""

from __future__ import annotations

from datetime import UTC, datetime

from src.agents.atp.atp_models import ATPActionType, ATPMessage, ATPMode
from src.agents.atp.atp_validator import ATPValidator

from .models import AtpEnvelope, GovernedContext, ServicePrincipal


class GovernanceDenied(PermissionError):
    """Raised when a request cannot satisfy a governance boundary."""


class GovernedGate:
    """Authorize server-owned capabilities only after strict ATP validation."""

    def authorize(
        self,
        principal: ServicePrincipal,
        envelope: AtpEnvelope,
        required_capability: str,
        required_scope: str | None = None,
    ) -> GovernedContext:
        """Validate ATP, enforce capability and scope policy, return accepted context."""
        atp_message = self._strict_message(envelope)
        validation = ATPValidator(strict=True).validate(atp_message)
        if not validation.is_valid:
            errors = "; ".join(validation.errors)
            raise GovernanceDenied(f"ATP validation failed: {errors}")

        if required_capability not in principal.capabilities:
            raise GovernanceDenied(
                f"principal lacks required capability: {required_capability}"
            )
        if required_scope is not None:
            self._require_scope(principal, required_scope)
        return GovernedContext(
            principal=principal,
            atp=envelope,
            capability=required_capability,
            scope=required_scope,
            accepted_at=datetime.now(UTC),
        )

    @staticmethod
    def _require_scope(principal: ServicePrincipal, required_scope: str) -> None:
        """Grant a scope only via its exact string or a server-recognized wildcard."""
        prefix, _, _ = required_scope.rpartition(":")
        wildcard = f"{prefix}:*" if prefix else None
        if required_scope in principal.capabilities:
            return
        if wildcard is not None and wildcard in principal.capabilities:
            return
        raise GovernanceDenied(f"principal lacks required scope: {required_scope}")

    @staticmethod
    def _strict_message(envelope: AtpEnvelope) -> ATPMessage:
        """Convert envelope values to canonical enums without coercion or fallback."""
        try:
            mode = ATPMode(envelope.mode)
            action_type = ATPActionType(envelope.action_type)
        except ValueError as error:
            raise GovernanceDenied("ATP envelope has unknown enum values") from error
        if mode is ATPMode.UNKNOWN or action_type is ATPActionType.UNKNOWN:
            raise GovernanceDenied("ATP envelope has unknown enum values")
        return ATPMessage(
            mode=mode,
            context=envelope.context,
            action_type=action_type,
            target_zone=envelope.target_zone,
            content=envelope.context,
        )
