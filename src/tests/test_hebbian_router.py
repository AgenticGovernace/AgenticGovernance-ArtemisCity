"""Unit tests for Hebbian-weighted routing.

Naming follows docs/TEST_PLAN.md: test_<module>_<function>_<scenario>.

Uses lightweight fakes for the registry and Hebbian manager so the routing
math is tested in isolation (no SQLite, no agents, no orchestrator).
"""

import pytest

from src.integration.hebbian_router import HebbianRouter, RoutingDecision


class _Agent:
    def __init__(self, name, capabilities):
        self.name = name
        self.capabilities = capabilities


class _Score:
    def __init__(self, composite):
        self._composite = composite

    @property
    def composite_score(self):
        return self._composite


class FakeRegistry:
    """Minimal stand-in exposing only what HebbianRouter reads."""

    def __init__(self, agents, composites, governance=None):
        self._agents = agents
        self.scores = {name: _Score(c) for name, c in composites.items()}
        self._gov = governance or {}

    def get_all_agents(self):
        return list(self._agents)

    def get_governance_state(self, name):
        return self._gov.get(name)

    def is_quarantined(self, name):
        state = self._gov.get(name)
        return bool(state and state.get("status") == "quarantined")


class FakeHebbian:
    def __init__(self, weights=None, raise_on=None):
        self._weights = weights or {}
        self._raise_on = set(raise_on or ())

    def get_agent_average_weight(self, name):
        if name in self._raise_on:
            raise RuntimeError("simulated hebbian failure")
        return self._weights.get(name, 0.0)


def _two_research_agents(composites, **kwargs):
    reg = FakeRegistry(
        [_Agent("A", ["research"]), _Agent("B", ["research"])],
        composites,
        **kwargs,
    )
    return reg


@pytest.mark.unit
def test_hebbian_router_cold_start_uses_composite():
    """With no Hebbian history, ranking collapses to composite score."""
    reg = _two_research_agents({"A": 0.9, "B": 0.6})
    router = HebbianRouter(reg, FakeHebbian(), alpha=0.3)
    assert router.route_name({"required_capability": "research"}) == "A"


@pytest.mark.unit
def test_hebbian_router_high_alpha_prefers_higher_weight():
    """At alpha=1 the agent with the higher learned weight wins."""
    reg = _two_research_agents({"A": 0.9, "B": 0.6})  # A better on paper
    heb = FakeHebbian({"A": 1.0, "B": 10.0})  # B proven in practice
    router = HebbianRouter(reg, heb, alpha=1.0)
    assert router.route_name({"required_capability": "research"}) == "B"


@pytest.mark.unit
def test_hebbian_router_alpha_zero_equals_composite():
    """At alpha=0 Hebbian weight is ignored; composite decides."""
    reg = _two_research_agents({"A": 0.4, "B": 0.8})
    heb = FakeHebbian({"A": 100.0, "B": 0.0})  # A has huge weight, ignored
    router = HebbianRouter(reg, heb, alpha=0.0)
    assert router.route_name({"required_capability": "research"}) == "B"


@pytest.mark.unit
def test_hebbian_router_excludes_quarantined_agent():
    """A quarantined agent is never routed to, even with the top score."""
    reg = _two_research_agents(
        {"A": 0.9, "B": 0.5}, governance={"A": {"status": "quarantined"}}
    )
    router = HebbianRouter(reg, FakeHebbian())
    assert router.route_name({"required_capability": "research"}) == "B"


@pytest.mark.unit
def test_hebbian_router_excludes_suspended_agent():
    """A suspended agent is also excluded from routing."""
    reg = _two_research_agents(
        {"A": 0.9, "B": 0.5}, governance={"A": {"status": "suspended"}}
    )
    router = HebbianRouter(reg, FakeHebbian())
    assert router.route_name({"required_capability": "research"}) == "B"


@pytest.mark.unit
def test_hebbian_router_no_capable_agent_raises():
    """No eligible agent for the capability raises the registry-style error."""
    reg = FakeRegistry([_Agent("A", ["research"])], {"A": 0.9})
    router = HebbianRouter(reg, FakeHebbian())
    with pytest.raises(ValueError, match="No agent found with the required capability"):
        router.route({"required_capability": "summarization"})


@pytest.mark.unit
def test_hebbian_router_missing_capability_raises():
    """A task without required_capability raises."""
    reg = FakeRegistry([_Agent("A", ["research"])], {"A": 0.9})
    router = HebbianRouter(reg, FakeHebbian())
    with pytest.raises(ValueError, match="must contain a 'required_capability'"):
        router.route({"title": "no capability here"})


@pytest.mark.unit
def test_hebbian_router_tolerates_broken_hebbian_source():
    """If the weight source raises (e.g. mocked), fall back to composite order."""
    reg = _two_research_agents({"A": 0.9, "B": 0.6})
    heb = FakeHebbian(raise_on={"A", "B"})  # every read raises
    router = HebbianRouter(reg, heb, alpha=0.5)
    assert router.route_name({"required_capability": "research"}) == "A"


@pytest.mark.unit
def test_hebbian_router_returns_decision_breakdown():
    """route() returns a RoutingDecision with a per-candidate breakdown."""
    reg = _two_research_agents({"A": 0.7, "B": 0.5})
    router = HebbianRouter(reg, FakeHebbian({"A": 2.0, "B": 4.0}), alpha=0.5)
    decision = router.route({"required_capability": "research"})
    assert isinstance(decision, RoutingDecision)
    assert decision.alpha == 0.5
    assert {c.name for c in decision.candidates} == {"A", "B"}
    assert decision.agent_name in {"A", "B"}
