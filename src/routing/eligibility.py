"""Hard eligibility gates that run before learned route ranking."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from src.routing.authorization import AuthorizationDecision


class EligibilityDenied(ValueError):
    """A stable fail-closed candidate-admission denial."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AgentEligibilityRecord:
    """Immutable registry projection containing every hard admission fact."""

    agent_id: str
    name: str
    capabilities: frozenset[str]
    tenant_ids: frozenset[str]
    scopes: frozenset[str]
    status: str
    quarantined: bool
    suspended: bool
    composite_score: float


@dataclass(frozen=True, slots=True)
class EligibleCandidate:
    """The complete immutable input accepted by production ranking."""

    agent_id: str
    name: str
    capabilities: frozenset[str]
    composite_score: float
    trust_score: float


class AgentEligibilityLookup(Protocol):
    """Port for the registry's current admission projections."""

    def list_admission_records(self) -> tuple[AgentEligibilityRecord, ...]:
        """Return one immutable snapshot of all registry admission records."""


class TrustEligibilityLookup(Protocol):
    """Port for current, decay-adjusted trust."""

    def score(self, agent_id: str) -> float:
        """Return the current trust score in the closed interval zero to one."""


class SandboxEligibilityPreflight(Protocol):
    """Read-only sandbox admission preflight."""

    def allows(
        self,
        agent_id: str,
        capabilities: frozenset[str],
        tenant_id: str,
    ) -> bool:
        """Return true only when dispatch can enter the candidate sandbox."""


class EligibilityFilter:
    """Apply all hard gates and emit only rankable candidates."""

    def __init__(
        self,
        *,
        registry: AgentEligibilityLookup,
        trust: TrustEligibilityLookup,
        sandbox: SandboxEligibilityPreflight,
        trust_floor: float,
    ) -> None:
        if not isfinite(trust_floor) or not 0.0 <= trust_floor <= 1.0:
            raise ValueError("trust_floor must be between zero and one")
        self._registry = registry
        self._trust = trust
        self._sandbox = sandbox
        self._trust_floor = trust_floor

    def candidates(
        self, authorized: AuthorizationDecision
    ) -> tuple[EligibleCandidate, ...]:
        """Return a deterministic immutable candidate tuple or deny."""
        try:
            records = self._registry.list_admission_records()
        except Exception as error:
            raise EligibilityDenied(
                "eligibility_lookup_failed", "agent registry admission lookup failed"
            ) from error
        if not isinstance(records, tuple):
            raise EligibilityDenied(
                "eligibility_lookup_failed",
                "agent registry did not return an immutable snapshot",
            )

        pinned = authorized.requested.agent
        if pinned is not None:
            records = tuple(
                record
                for record in records
                if record.name == pinned or record.agent_id == pinned
            )

        requester_tenant = authorized.authority.requester.principal.identity.tenant_id
        eligible: list[EligibleCandidate] = []
        seen: set[str] = set()
        for record in sorted(records, key=lambda candidate: candidate.name):
            if record.agent_id in seen:
                continue
            seen.add(record.agent_id)
            capabilities = record.capabilities.intersection(authorized.capabilities)
            if not capabilities:
                continue
            if requester_tenant not in record.tenant_ids:
                continue
            if not capabilities.intersection(record.scopes):
                continue
            if record.status != "active":
                continue
            if record.quarantined or record.suspended:
                continue
            if not isfinite(record.composite_score) or not (
                0.0 <= record.composite_score <= 1.0
            ):
                continue
            try:
                trust_score = float(self._trust.score(record.agent_id))
            except Exception:  # noqa: BLE001, S112 - missing trust denies admission
                continue
            if not isfinite(trust_score) or not 0.0 <= trust_score <= 1.0:
                continue
            if trust_score < self._trust_floor:
                continue
            try:
                sandbox_allowed = self._sandbox.allows(
                    record.agent_id, frozenset(capabilities), requester_tenant
                )
            except Exception:  # noqa: BLE001, S112 - failed preflight denies admission
                continue
            if not sandbox_allowed:
                continue
            eligible.append(
                EligibleCandidate(
                    agent_id=record.agent_id,
                    name=record.name,
                    capabilities=frozenset(capabilities),
                    composite_score=record.composite_score,
                    trust_score=trust_score,
                )
            )

        if not eligible:
            if pinned is not None:
                raise EligibilityDenied(
                    "pinned_agent_ineligible",
                    "the pinned agent did not pass every eligibility gate",
                )
            raise EligibilityDenied(
                "no_eligible_agent", "no agent passed every eligibility gate"
            )
        return tuple(eligible)
