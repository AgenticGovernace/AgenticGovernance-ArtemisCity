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
        records = self._validate_snapshot(records)

        pinned = authorized.requested.agent
        if pinned is not None:
            matches = tuple(
                record
                for record in records
                if record.name == pinned or record.agent_id == pinned
            )
            if len(matches) > 1:
                raise EligibilityDenied(
                    "pinned_agent_ambiguous",
                    "the pinned identifier resolves to multiple registry records",
                )
            if not matches:
                raise EligibilityDenied(
                    "pinned_agent_ineligible",
                    "the pinned agent is absent from the registry snapshot",
                )
            records = matches

        requester_tenant = authorized.authority.requester.principal.identity.tenant_id
        eligible: list[EligibleCandidate] = []
        for record in sorted(records, key=lambda candidate: candidate.name):
            capabilities = record.capabilities.intersection(record.scopes).intersection(
                authorized.capabilities
            )
            if not capabilities:
                continue
            if requester_tenant not in record.tenant_ids:
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

    @staticmethod
    def _validate_snapshot(
        records: tuple[object, ...],
    ) -> tuple[AgentEligibilityRecord, ...]:
        validated: list[AgentEligibilityRecord] = []
        agent_ids: set[str] = set()
        names: set[str] = set()
        for record in records:
            if not isinstance(record, AgentEligibilityRecord):
                raise EligibilityDenied(
                    "eligibility_lookup_failed",
                    "agent registry returned a malformed admission record",
                )
            string_fields = (record.agent_id, record.name, record.status)
            set_fields = (
                record.capabilities,
                record.tenant_ids,
                record.scopes,
            )
            valid_strings = all(
                type(value) is str and bool(value.strip()) for value in string_fields
            )
            valid_sets = all(
                type(values) is frozenset
                and all(type(value) is str and bool(value.strip()) for value in values)
                for values in set_fields
            )
            valid_bools = (
                type(record.quarantined) is bool and type(record.suspended) is bool
            )
            valid_score = (
                type(record.composite_score) is float
                and isfinite(record.composite_score)
                and 0.0 <= record.composite_score <= 1.0
            )
            if not (valid_strings and valid_sets and valid_bools and valid_score):
                raise EligibilityDenied(
                    "eligibility_lookup_failed",
                    "agent registry returned a malformed admission record",
                )
            if record.agent_id in agent_ids or record.name in names:
                raise EligibilityDenied(
                    "eligibility_lookup_failed",
                    "agent registry returned duplicate canonical identity",
                )
            agent_ids.add(record.agent_id)
            names.add(record.name)
            validated.append(record)
        return tuple(validated)
