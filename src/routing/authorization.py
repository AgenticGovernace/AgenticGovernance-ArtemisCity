"""Effective-capability authorization for the Artemis Routing Kernel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, overload

from src.auth.contracts import AuthorityContextV1
from src.auth.delegation import DelegationGrantLookup, DelegationGrantV1
from src.routing.contracts import (
    AuthorizedRouteRequestV1,
    DelegationContextV1,
    RequestedConstraintsV1,
    ResolvedIntentV1,
)


class AuthorizationDenied(ValueError):
    """A stable fail-closed authorization denial."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DelegationBudgetPolicy(Protocol):
    """Admission port for the current state of a budget reservation."""

    def reservation_is_active(self, reservation_id: str) -> bool:
        """Return true only while the referenced reservation may dispatch."""


class AuthorizationCapabilityPolicy(Protocol):
    """Current target-zone and Artemis capability policy."""

    def target_zone_capabilities(self, target_zone: str) -> frozenset[str]:
        """Return current capabilities permitted in one target zone."""

    def artemis_capabilities(self, intent: ResolvedIntentV1) -> frozenset[str]:
        """Return current Artemis capabilities permitted for this intent."""


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Verified inputs narrowed to the capabilities Artemis may route."""

    authority: AuthorityContextV1
    intent: ResolvedIntentV1
    requested: RequestedConstraintsV1
    capabilities: frozenset[str]
    delegation_grant: DelegationGrantV1 | None


class ArtemisAuthorizer:
    """Intersect verified authority, delegation, intent, and current policy."""

    def __init__(
        self,
        *,
        grant_lookup: DelegationGrantLookup,
        budget_policy: DelegationBudgetPolicy,
        capability_policy: AuthorizationCapabilityPolicy,
        clock: Callable[[], datetime],
    ) -> None:
        self._grant_lookup = grant_lookup
        self._budget_policy = budget_policy
        self._capability_policy = capability_policy
        self._clock = clock

    @overload
    def authorize(
        self,
        authority: AuthorityContextV1,
        intent: ResolvedIntentV1,
        requested: RequestedConstraintsV1,
    ) -> AuthorizationDecision: ...

    @overload
    def authorize(
        self,
        authority: AuthorizedRouteRequestV1,
        intent: None = None,
        requested: None = None,
    ) -> AuthorizationDecision: ...

    def authorize(
        self,
        authority: AuthorityContextV1 | AuthorizedRouteRequestV1,
        intent: ResolvedIntentV1 | None = None,
        requested: RequestedConstraintsV1 | None = None,
    ) -> AuthorizationDecision:
        """Return the effective capability intersection or a stable denial."""
        delegation_context: DelegationContextV1 | None = None
        if isinstance(authority, AuthorizedRouteRequestV1):
            if intent is not None or requested is not None:
                raise TypeError("route request cannot be combined with split inputs")
            request = authority
            authority = request.authority
            intent = request.resolved_intent
            requested = request.envelope.requested_constraints
            delegation_context = request.envelope.delegation
        elif intent is None or requested is None:
            raise TypeError("split authorization requires intent and constraints")

        grant = self._validated_grant(authority, intent, delegation_context)

        effective = authority.requester.principal.capability.granted_scopes
        effective = effective.intersection(
            authority.actor.principal.capability.granted_scopes
        )
        if grant is not None:
            effective = effective.intersection(grant.allowed_capabilities)
        effective = effective.intersection({intent.capability})
        if requested.capability is not None:
            effective = effective.intersection({requested.capability})

        try:
            target_capabilities = self._capability_policy.target_zone_capabilities(
                intent.target_zone
            )
            artemis_capabilities = self._capability_policy.artemis_capabilities(intent)
        except Exception as error:
            raise AuthorizationDenied(
                "unauthorized_capability",
                "current authorization policy is unavailable",
            ) from error

        effective = effective.intersection(target_capabilities)
        effective = effective.intersection(artemis_capabilities)
        if not effective:
            raise AuthorizationDenied(
                "unauthorized_capability",
                "verified authority does not permit the resolved capability",
            )
        return AuthorizationDecision(
            authority=authority,
            intent=intent,
            requested=requested,
            capabilities=frozenset(effective),
            delegation_grant=grant,
        )

    def _validated_grant(
        self,
        authority: AuthorityContextV1,
        intent: ResolvedIntentV1,
        delegation_context: DelegationContextV1 | None,
    ) -> DelegationGrantV1 | None:
        reference = authority.delegation
        if (
            delegation_context is not None
            and delegation_context.grant_id is not None
            and reference is None
        ):
            raise AuthorizationDenied(
                "delegation_grant_missing",
                "child delegation is absent from verified authority",
            )
        if reference is None:
            return None
        if delegation_context is not None and delegation_context.grant_id is None:
            raise AuthorizationDenied(
                "delegation_grant_non_narrowing",
                "root route cannot carry delegated authority",
            )
        grant_id = reference.grant_id
        grant_hash = reference.grant_hash
        if grant_id is None or grant_hash is None:  # protected by the V1 contract
            raise AuthorizationDenied(
                "delegation_grant_missing", "delegation reference is incomplete"
            )
        if delegation_context is not None:
            if delegation_context.grant_id != grant_id:
                raise AuthorizationDenied(
                    "delegation_grant_non_narrowing",
                    "child delegation references a different persisted grant",
                )
            if delegation_context.grant_hash != grant_hash:
                raise AuthorizationDenied(
                    "delegation_grant_hash_mismatch",
                    "child delegation hash differs from verified authority",
                )
        try:
            grant = self._grant_lookup.get(grant_id)
        except Exception as error:
            raise AuthorizationDenied(
                "delegation_grant_missing",
                "persisted delegation grant is unavailable",
            ) from error
        if grant is None:
            raise AuthorizationDenied(
                "delegation_grant_missing", "persisted delegation grant was not found"
            )
        if grant.grant_hash != grant_hash:
            raise AuthorizationDenied(
                "delegation_grant_hash_mismatch",
                "delegation reference does not match the persisted grant",
            )
        if self._clock() >= grant.expires_at:
            raise AuthorizationDenied(
                "delegation_grant_expired", "delegation grant has expired"
            )
        if not self._grant_bounds_current_request(
            grant, authority, intent, delegation_context
        ):
            raise AuthorizationDenied(
                "delegation_grant_non_narrowing",
                "delegation grant does not bound the current child request",
            )
        try:
            active_budget = self._budget_policy.reservation_is_active(
                grant.budget_reservation_id
            )
        except Exception as error:
            raise AuthorizationDenied(
                "delegation_budget_unavailable",
                "delegation budget reservation is unavailable",
            ) from error
        if not active_budget:
            raise AuthorizationDenied(
                "delegation_budget_unavailable",
                "delegation budget reservation is inactive or exhausted",
            )
        return grant

    @staticmethod
    def _grant_bounds_current_request(
        grant: DelegationGrantV1,
        authority: AuthorityContextV1,
        intent: ResolvedIntentV1,
        delegation_context: DelegationContextV1 | None,
    ) -> bool:
        requester = authority.requester
        actor = authority.actor
        references_match = (
            grant.requester_principal_ref == requester.principal.identity.agent_id
            and grant.requester_auth_receipt_id
            == requester.auth_receipt.source.receipt_id
            and grant.requester_auth_receipt_hash
            == requester.auth_receipt.source.record_hash
            and grant.actor_principal_ref == actor.principal.identity.agent_id
            and grant.actor_auth_receipt_id == actor.auth_receipt.source.receipt_id
            and grant.actor_auth_receipt_hash == actor.auth_receipt.source.record_hash
        )
        context_matches = delegation_context is None or all(
            (
                delegation_context.grant_id == grant.grant_id,
                delegation_context.grant_hash == grant.grant_hash,
                delegation_context.root_task_id == grant.root_task_id,
                delegation_context.parent_task_id == grant.parent_task_id,
                delegation_context.parent_outcome_id == grant.parent_outcome_id,
                0 < delegation_context.depth <= grant.depth_limit,
            )
        )
        return (
            references_match
            and context_matches
            and all(
                (
                    intent.mode in grant.allowed_modes,
                    intent.action_type in grant.allowed_action_types,
                    intent.capability in grant.allowed_capabilities,
                    intent.target_zone in grant.allowed_target_zones,
                )
            )
        )
