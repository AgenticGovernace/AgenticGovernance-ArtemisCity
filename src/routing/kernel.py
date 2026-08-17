"""The shared Artemis Routing Kernel.

Phase 4 of the routing-kernel consolidation requires that every active ingress
delegate exactly once to one routing service, rather than each re-implementing
capability resolution and candidate discovery. This module is that service: it
composes the four reviewed stages in their required order.

    IntentResolver -> ArtemisAuthorizer -> EligibilityFilter -> HebbianRanker

The ordering is load-bearing, not stylistic. Governance and trust eligibility
must run *before* learned ranking, so a quarantined or low-trust agent can never
be rescued by a strong Hebbian weight.

Trusted in-process ingresses (the CLI, orchestrator-internal child dispatch)
have no HTTP credential to present. Rather than letting those callers bypass the
kernel -- which is exactly the forked-source-of-truth problem this phase exists
to remove -- they present an explicit, clearly labelled system authority built
by :func:`system_authority`. It is a local trust assertion, not authentication,
and it is deliberately visible in the resulting authority context so an audit can
tell a system-originated route from an authenticated one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Optional

from src.auth.contracts import (AuthorityContextV1, AuthReceiptSourceV1,
                                AuthReceiptV1, PrincipalCapabilityV1,
                                PrincipalIdentityV1, PrincipalV1,
                                VerifiedPartyV1)
from src.integration.hebbian_router import (DEFAULT_ALPHA, DEFAULT_BETA,
                                            DEFAULT_TRUST_FLOOR, NEUTRAL_PRIOR,
                                            HebbianRanker, RoutingDecision)
from src.routing.adapters import (DEFAULT_TENANT_ID, RegistryAdmissionLookup,
                                  SandboxAdmissionPreflight,
                                  TrustAdmissionLookup)
from src.routing.authorization import (ArtemisAuthorizer,
                                       AuthorizationDecision,
                                       AuthorizationDenied)
from src.routing.authorization_policy import CapabilityPolicyAdapter
from src.routing.contracts import (RequestedConstraintsV1, ResolvedIntentV1,
                                   TaskIntentV1)
from src.routing.delegation_store import SqliteDelegationStore
from src.routing.eligibility import EligibilityDenied, EligibilityFilter
from src.routing.intent import IntentDenied, IntentResolver

#: Stable denial code meaning "this capability has no reviewed ATP execution
#: domain", as distinct from "policy refused this capability".
CAPABILITY_OUTSIDE_REVIEWED_DOMAIN = "capability_outside_reviewed_domain"

SYSTEM_ISSUER = "artemis.local/system"
SYSTEM_AUDIENCE = "artemis.routing-kernel"
SYSTEM_PRINCIPAL_LIFETIME = timedelta(minutes=15)


class RoutingKernelDenied(ValueError):
    """A stable routing-boundary denial carrying the originating stage."""

    def __init__(self, code: str, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage


def system_authority(
    *,
    granted_scopes: frozenset[str],
    agent_id: str = "artemis-system",
    tenant_id: str = DEFAULT_TENANT_ID,
    now: Optional[datetime] = None,
) -> AuthorityContextV1:
    """Build the local trust assertion used by trusted in-process ingresses.

    This is not authentication. It exists so CLI and orchestrator-internal
    dispatch traverse the same kernel as authenticated HTTP traffic instead of
    forking into a second routing path. Every field names the system issuer
    explicitly so a route taken under this authority is identifiable in audit.
    """
    if not granted_scopes:
        raise ValueError("system authority requires at least one granted scope")

    verified_at = (now or datetime.now(UTC)).astimezone(UTC)
    expires_at = verified_at + SYSTEM_PRINCIPAL_LIFETIME

    principal = PrincipalV1(
        identity=PrincipalIdentityV1(
            actor_issuer=SYSTEM_ISSUER,
            actor_subject_ref=agent_id,
            agent_id=agent_id,
            tenant_id=tenant_id,
            certificate_issuer=SYSTEM_ISSUER,
            certificate_serial="system-local",
            certificate_thumbprint="system-local",
            request_key_id="system-local",
            request_key_jkt="system-local",
        ),
        capability=PrincipalCapabilityV1(
            token_issuer=SYSTEM_ISSUER,
            audience=SYSTEM_AUDIENCE,
            token_key_id="system-local",
            token_jti_ref=f"system-local:{verified_at.isoformat()}",
            granted_scopes=granted_scopes,
        ),
        verified_at=verified_at,
        expires_at=expires_at,
    )
    receipt = AuthReceiptV1(
        request_id=f"system-local:{verified_at.isoformat()}",
        authentication="authenticated",
        principal=principal,
        reason_code=None,
        verified_at=verified_at,
        source=AuthReceiptSourceV1(
            format="artemis.system-authority/1",
            receipt_id=f"system-local:{verified_at.isoformat()}",
            record_hash="system-local",
            receipt_key_id="system-local",
            signer_namespace=SYSTEM_ISSUER,
            canonical_receipt={
                "issuer": SYSTEM_ISSUER,
                "origin": "in-process",
                "verified_at": verified_at.isoformat(),
            },
        ),
    )
    party = VerifiedPartyV1(principal=principal, auth_receipt=receipt)
    return AuthorityContextV1(requester=party, actor=party, delegation=None)


@dataclass(frozen=True, slots=True)
class KernelRoute:
    """The complete governed outcome of one routing pass."""

    decision: RoutingDecision
    authorization: AuthorizationDecision
    resolved_intent: ResolvedIntentV1


class RoutingKernel:
    """Compose intent resolution, authorization, eligibility, and ranking."""

    def __init__(
        self,
        *,
        intent_resolver: IntentResolver,
        authorizer: ArtemisAuthorizer,
        eligibility: EligibilityFilter,
        ranker: HebbianRanker,
        capability_policy: CapabilityPolicyAdapter,
    ) -> None:
        self.intent_resolver = intent_resolver
        self.authorizer = authorizer
        self.eligibility = eligibility
        self.ranker = ranker
        self.capability_policy = capability_policy

    @classmethod
    def build(
        cls,
        registry: Any,
        hebbian: Any,
        *,
        trust_interface: Any,
        alpha: float = DEFAULT_ALPHA,
        beta: float = DEFAULT_BETA,
        neutral_prior: float = NEUTRAL_PRIOR,
        trust_floor: float = DEFAULT_TRUST_FLOOR,
        delegation_store: Optional[SqliteDelegationStore] = None,
        clock: Optional[Callable[[], datetime]] = None,
        policy_path: Optional[str] = None,
    ) -> RoutingKernel:
        """Construct a kernel wired to the live Artemis subsystems."""
        store = delegation_store or SqliteDelegationStore()
        capability_policy = CapabilityPolicyAdapter.load(policy_path)
        return cls(
            intent_resolver=IntentResolver.default(),
            authorizer=ArtemisAuthorizer(
                grant_lookup=store,
                budget_policy=store,
                capability_policy=capability_policy,
                clock=clock or (lambda: datetime.now(UTC)),
            ),
            eligibility=EligibilityFilter(
                registry=RegistryAdmissionLookup(registry),
                trust=TrustAdmissionLookup(trust_interface),
                sandbox=SandboxAdmissionPreflight(registry),
                trust_floor=trust_floor,
            ),
            ranker=HebbianRanker(
                hebbian,
                alpha=alpha,
                neutral_prior=neutral_prior,
                beta=beta,
            ),
            capability_policy=capability_policy,
        )

    @property
    def routable_capabilities(self) -> frozenset[str]:
        """Return every capability Artemis policy currently permits routing."""
        return self.capability_policy.policy.artemis_capabilities

    def system_authority(self, **overrides: Any) -> AuthorityContextV1:
        """Build a system authority scoped to current Artemis policy."""
        overrides.setdefault("granted_scopes", self.routable_capabilities)
        return system_authority(**overrides)

    def route(
        self,
        *,
        content: str,
        authority: AuthorityContextV1,
        typed_intent: Optional[TaskIntentV1] = None,
        requested: Optional[RequestedConstraintsV1] = None,
        route_request: Any = None,
    ) -> KernelRoute:
        """Resolve, authorize, filter, and rank one task in the required order.

        Args:
            content: The raw task text, carrying ATP headers when present.
            authority: Verified authority, or a system authority for trusted
                in-process ingress.
            typed_intent: Trusted typed-adapter intent for non-ATP tasks.
            requested: Caller constraints, which may only narrow policy.
            route_request: An ``AuthorizedRouteRequestV1`` for delegated child
                routes; when supplied it replaces the split authority inputs.

        Returns:
            KernelRoute: The ranked decision plus its authorization evidence.

        Raises:
            RoutingKernelDenied: On any stage denial, tagged with the stage.
        """
        constraints = requested or RequestedConstraintsV1()

        try:
            resolved_intent = self.intent_resolver.resolve(
                content, typed_intent=typed_intent, requested=constraints
            )
        except IntentDenied as denied:
            raise RoutingKernelDenied(
                denied.code, denied.message, stage="intent"
            ) from denied

        try:
            if route_request is not None:
                authorized = self.authorizer.authorize(route_request)
            else:
                authorized = self.authorizer.authorize(
                    authority, resolved_intent, constraints
                )
        except AuthorizationDenied as denied:
            raise RoutingKernelDenied(
                denied.code, denied.message, stage="authorization"
            ) from denied

        try:
            candidates = self.eligibility.candidates(authorized)
        except EligibilityDenied as denied:
            raise RoutingKernelDenied(
                denied.code, denied.message, stage="eligibility"
            ) from denied

        try:
            decision = self.ranker.rank(authorized, candidates)
        except (TypeError, ValueError) as error:
            raise RoutingKernelDenied(
                "ranking_failed", str(error), stage="ranking"
            ) from error

        return KernelRoute(
            decision=decision,
            authorization=authorized,
            resolved_intent=authorized.intent,
        )

    # -- Orchestrator compatibility ----------------------------------------

    def typed_intent_for_capability(
        self,
        capability: str,
        *,
        context: str,
        target_zone: str = "unspecified",
    ) -> TaskIntentV1:
        """Derive a trusted typed-adapter intent for a non-ATP capability.

        Tasks that never carried ATP headers still need an intent the reviewed
        policy recognizes. Rather than hard-coding a mode/action pair, this
        searches the loaded policy for the first reviewed pair whose authorized
        domain already contains the requested capability. The capability
        therefore cannot be widened by the search -- if no reviewed pair
        authorizes it, no intent is produced.
        """
        pairs = self.intent_resolver.policy.pairs
        for mode in sorted(pairs):
            for action_type in sorted(pairs[mode]):
                if capability in pairs[mode][action_type]:
                    return TaskIntentV1(
                        mode=mode,
                        action_type=action_type,
                        context=context,
                        target_zone=target_zone,
                        source="typed-adapter",
                    )
        # Distinct from ``unauthorized_capability``: the capability was not
        # refused, it simply has no reviewed ATP execution domain at all.
        # Widening the domain requires editing ``_REVIEWED_PAIRS`` under review
        # -- ``IntentPolicy.load`` rejects a YAML-only change by design -- so
        # this is a governance gap, not a caller error. Ingresses use this code
        # to route legacy capabilities through the compatibility path instead
        # of silently rerouting the task to an unrelated agent.
        raise RoutingKernelDenied(
            CAPABILITY_OUTSIDE_REVIEWED_DOMAIN,
            f"no reviewed ATP pair authorizes capability {capability!r}",
            stage="intent",
        )

    def route_task_context(
        self,
        task: dict[str, Any],
        *,
        authority: Optional[AuthorityContextV1] = None,
        fallback_capability: Optional[str] = None,
    ) -> KernelRoute:
        """Route one orchestrator task dict through the full kernel.

        This is the compatibility seam that lets existing ingresses reach the
        kernel without each rebuilding intent and authority. ATP-formatted tasks
        resolve their own intent from headers; non-ATP tasks are given a trusted
        typed-adapter intent derived from the reviewed policy.

        Args:
            task: The orchestrator task context.
            authority: Verified authority; a system authority is built when the
                caller is a trusted in-process ingress and supplies none.
            fallback_capability: Capability to retry once when the requested one
                has no eligible agent. ``None`` keeps strict matching.

        Returns:
            KernelRoute: The ranked decision plus its authorization evidence.
        """
        raw_content = task.get("atp_raw") or task.get("content") or ""
        context = str(task.get("context") or raw_content or "task").strip() or "task"
        target_zone = str(task.get("target_zone") or "unspecified").strip()
        capability = task.get("required_capability")
        pinned_agent = task.get("agent") or task.get("agent_name")

        resolved_authority = authority or self.system_authority()

        def attempt(selected_capability: Optional[str]) -> KernelRoute:
            constraints = RequestedConstraintsV1(
                capability=selected_capability or None,
                agent=str(pinned_agent) if pinned_agent else None,
            )
            from src.agents.atp.atp_parser import ATPParser

            is_atp = bool(raw_content) and ATPParser().is_atp_formatted(raw_content)
            typed_intent = None
            content = raw_content
            if not is_atp:
                if not selected_capability:
                    raise RoutingKernelDenied(
                        "missing_typed_intent",
                        "non-ATP tasks require a capability to derive intent",
                        stage="intent",
                    )
                typed_intent = self.typed_intent_for_capability(
                    selected_capability, context=context, target_zone=target_zone
                )
                content = context
            return self.route(
                content=content,
                authority=resolved_authority,
                typed_intent=typed_intent,
                requested=constraints,
            )

        try:
            return attempt(str(capability) if capability else None)
        except RoutingKernelDenied as denied:
            # A capability with no reviewed domain must NOT fall back: retrying
            # as ``llm_chat`` would silently hand a research or coordination
            # task to a general chat agent. Surface it so the caller decides.
            if denied.code == CAPABILITY_OUTSIDE_REVIEWED_DOMAIN:
                raise
            if (
                fallback_capability
                and denied.stage in {"eligibility", "intent"}
                and fallback_capability != capability
                and not pinned_agent
            ):
                return attempt(fallback_capability)
            raise


__all__ = [
    "KernelRoute",
    "RoutingKernel",
    "RoutingKernelDenied",
    "system_authority",
]
