"""Eligibility tests for filtering all hard gates before learned ranking."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.routing.authorization import AuthorizationDecision
from src.routing.contracts import RequestedConstraintsV1
from src.routing.eligibility import (
    AgentEligibilityRecord,
    EligibilityDenied,
    EligibilityFilter,
)

from .test_routing_authorization import _authority, _intent


def _authorized(*, pinned: str | None = None) -> AuthorizationDecision:
    return AuthorizationDecision(
        authority=_authority(
            requester_scopes={"llm_chat"},
            actor_scopes={"llm_chat"},
        ),
        intent=_intent(),
        requested=RequestedConstraintsV1(agent=pinned),
        capabilities=frozenset({"llm_chat"}),
        delegation_grant=None,
    )


def _record(name: str = "eligible-agent", **changes: object) -> AgentEligibilityRecord:
    record = AgentEligibilityRecord(
        agent_id=f"agent:{name}",
        name=name,
        capabilities=frozenset({"llm_chat"}),
        tenant_ids=frozenset({"tenant:city"}),
        scopes=frozenset({"llm_chat"}),
        status="active",
        quarantined=False,
        suspended=False,
        composite_score=0.5,
    )
    return replace(record, **changes)


class _Registry:
    def __init__(self, records: tuple[AgentEligibilityRecord, ...], *, broken=False):
        self.records = records
        self.broken = broken

    def list_admission_records(self) -> tuple[AgentEligibilityRecord, ...]:
        if self.broken:
            raise RuntimeError("registry unavailable")
        return self.records


class _Trust:
    def __init__(self, scores: dict[str, float] | None = None, *, broken=False):
        self.scores = scores or {}
        self.broken = broken

    def score(self, agent_id: str) -> float:
        if self.broken:
            raise RuntimeError("trust unavailable")
        return self.scores.get(agent_id, 0.8)


class _Sandbox:
    def __init__(self, denied: set[str] | None = None, *, broken=False):
        self.denied = denied or set()
        self.broken = broken

    def allows(
        self, agent_id: str, capabilities: frozenset[str], tenant_id: str
    ) -> bool:
        if self.broken:
            raise RuntimeError("sandbox unavailable")
        return agent_id not in self.denied


def _filter(
    records: tuple[AgentEligibilityRecord, ...],
    *,
    trust: _Trust | None = None,
    sandbox: _Sandbox | None = None,
    trust_floor: float = 0.5,
    registry_broken: bool = False,
) -> EligibilityFilter:
    return EligibilityFilter(
        registry=_Registry(records, broken=registry_broken),
        trust=trust or _Trust(),
        sandbox=sandbox or _Sandbox(),
        trust_floor=trust_floor,
    )


def test_eligibility_filters_every_hard_gate_before_ranking() -> None:
    """Weakening any hard gate would put a forbidden agent into the tuple."""
    records = (
        _record(),
        _record("wrong-capability", capabilities=frozenset({"reasoning"})),
        _record("wrong-tenant", tenant_ids=frozenset({"tenant:other"})),
        _record("wrong-scope", scopes=frozenset({"reasoning"})),
        _record("inactive", status="inactive"),
        _record("quarantined", quarantined=True),
        _record("suspended", suspended=True),
        _record("low-trust"),
        _record("sandbox-denied"),
    )
    candidates = _filter(
        records,
        trust=_Trust({"agent:low-trust": 0.1}),
        sandbox=_Sandbox({"agent:sandbox-denied"}),
    ).candidates(_authorized())

    assert isinstance(candidates, tuple)
    assert [candidate.name for candidate in candidates] == ["eligible-agent"]
    assert candidates[0].capabilities == frozenset({"llm_chat"})


def test_pinned_quarantined_agent_is_denied() -> None:
    """Pinning must never bypass quarantine."""
    with pytest.raises(EligibilityDenied) as denied:
        _filter(
            (
                _record("eligible-agent"),
                _record("pinned-agent", quarantined=True),
            )
        ).candidates(_authorized(pinned="pinned-agent"))

    assert denied.value.code == "pinned_agent_ineligible"


@pytest.mark.parametrize("failure", ["registry", "trust", "sandbox"])
def test_eligibility_fails_closed_when_an_admission_port_raises(failure: str) -> None:
    """Missing admission evidence must not be replaced by a neutral prior."""
    filter_ = _filter(
        (_record(),),
        trust=_Trust(broken=failure == "trust"),
        sandbox=_Sandbox(broken=failure == "sandbox"),
        registry_broken=failure == "registry",
    )

    with pytest.raises(EligibilityDenied) as denied:
        filter_.candidates(_authorized())

    assert denied.value.code in {"eligibility_lookup_failed", "no_eligible_agent"}


def test_eligibility_rejects_non_finite_scores() -> None:
    """NaN ranking input must fail admission rather than poison deterministic order."""
    with pytest.raises(EligibilityDenied) as denied:
        _filter((_record(composite_score=float("nan")),)).candidates(_authorized())

    assert denied.value.code == "no_eligible_agent"
