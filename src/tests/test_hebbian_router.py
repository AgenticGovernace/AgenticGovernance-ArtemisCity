"""Unit tests for Hebbian-weighted routing.

Naming follows docs/TEST_PLAN.md: test_<module>_<function>_<scenario>.

Uses lightweight fakes for the registry and Hebbian manager so the routing
math is tested in isolation (no SQLite, no agents, no orchestrator).
"""

from math import isfinite

import pytest

from src.integration.hebbian_router import HebbianRanker, HebbianRouter, RoutingDecision
from src.routing.eligibility import EligibleCandidate

from .test_routing_eligibility import _authorized, _filter, _record


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
    def __init__(
        self,
        weights=None,
        raise_on=None,
        scoped_weights=None,
        stability=None,
    ):
        self._weights = weights or {}
        self._raise_on = set(raise_on or ())
        self._scoped_weights = scoped_weights or {}
        self._stability = stability or {}

    def get_agent_average_weight(self, name):
        if name in self._raise_on:
            raise RuntimeError("simulated hebbian failure")
        return self._weights.get(name, 0.0)

    def get_task_type_weight(self, name, task_type):
        if name in self._raise_on:
            raise RuntimeError("simulated hebbian failure")
        return self._scoped_weights.get((name, task_type))

    def has_task_type_history(self, name):
        return any(agent_name == name for agent_name, _ in self._scoped_weights)

    def get_stability_signal(self, name, task_type):
        return self._stability.get(
            (name, task_type),
            {"oscillation_rate": 0.0, "alert_active": False, "sample_count": 0},
        )


class _TrustScore:
    def __init__(self, score):
        self.score = score


class FakeTrust:
    """Minimal stand-in for TrustInterface.get_trust_score(name)."""

    def __init__(self, scores=None, raise_on=None):
        self._scores = scores or {}
        self._raise_on = set(raise_on or ())

    def get_trust_score(self, name, entity_type="agent"):
        if name in self._raise_on:
            raise RuntimeError("simulated trust failure")
        return _TrustScore(self._scores.get(name, 0.8))


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
def test_hebbian_router_alpha_blend_uses_one_minus_alpha():
    registry = FakeRegistry([_Agent("A", ["research"])], {"A": 0.5})
    hebbian = FakeHebbian(scoped_weights={("A", "research"): 1.0})
    decision = HebbianRouter(registry, hebbian, alpha=0.3).route(
        {"required_capability": "research"}
    )

    assert decision.candidates[0].blended == pytest.approx(0.65)


@pytest.mark.unit
def test_hebbian_router_prefers_task_type_history_over_global_average():
    """Routing uses scoped performance instead of unrelated task history."""
    reg = _two_research_agents({"A": 0.6, "B": 0.6})
    heb = FakeHebbian(
        weights={"A": 100.0, "B": 1.0},
        scoped_weights={("A", "research"): 1.0, ("B", "research"): 10.0},
    )
    router = HebbianRouter(reg, heb, alpha=1.0)
    assert router.route_name({"required_capability": "research"}) == "B"


@pytest.mark.unit
def test_hebbian_router_legacy_history_fallback_when_scope_is_cold():
    """Existing databases retain their agent-average routing signal."""
    reg = _two_research_agents({"A": 0.6, "B": 0.6})
    heb = FakeHebbian(weights={"A": 1.0, "B": 10.0})
    router = HebbianRouter(reg, heb, alpha=1.0)
    assert router.route_name({"required_capability": "research"}) == "B"


@pytest.mark.unit
def test_hebbian_router_new_scope_does_not_inherit_unrelated_history():
    """A migrated agent receives the neutral prior for an unseen task type."""
    reg = _two_research_agents({"A": 0.9, "B": 0.6})
    heb = FakeHebbian(
        weights={"A": 100.0, "B": 0.0},
        scoped_weights={("A", "summarization"): 100.0},
    )
    router = HebbianRouter(reg, heb, alpha=0.5)

    decision = router.route({"required_capability": "research"})

    assert decision.agent_name == "A"
    candidate_a = next(c for c in decision.candidates if c.name == "A")
    assert candidate_a.hebbian_weight == 0.0
    assert candidate_a.hebbian_norm == 0.5


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
def test_hebbian_router_falls_back_for_unmatched_capability():
    """An unmatched capability routes to the configured fallback agent."""
    reg = FakeRegistry(
        [_Agent("Research", ["web_search"]), _Agent("LLM", ["llm_chat"])],
        {"Research": 0.9, "LLM": 0.5},
    )
    router = HebbianRouter(reg, FakeHebbian(), fallback_capability="llm_chat")
    decision = router.route({"required_capability": "chitchat"})
    assert decision.agent_name == "LLM"
    assert decision.fallback_from == "chitchat"


@pytest.mark.unit
def test_hebbian_router_falls_back_for_missing_capability():
    """A task with no capability routes to the fallback when configured."""
    reg = FakeRegistry([_Agent("LLM", ["llm_chat"])], {"LLM": 0.5})
    router = HebbianRouter(reg, FakeHebbian(), fallback_capability="llm_chat")
    assert router.route_name({"title": "just chat"}) == "LLM"


@pytest.mark.unit
def test_hebbian_router_no_fallback_still_raises():
    """Without a fallback, an unmatched capability still raises (legacy)."""
    reg = FakeRegistry([_Agent("LLM", ["llm_chat"])], {"LLM": 0.5})
    router = HebbianRouter(reg, FakeHebbian())  # no fallback_capability
    with pytest.raises(ValueError, match="No agent found with the required capability"):
        router.route({"required_capability": "chitchat"})


@pytest.mark.unit
def test_hebbian_router_fallback_excluded_when_blocked():
    """If the fallback agent is quarantined, routing raises rather than using it."""
    reg = FakeRegistry(
        [_Agent("LLM", ["llm_chat"])],
        {"LLM": 0.5},
        governance={"LLM": {"status": "quarantined"}},
    )
    router = HebbianRouter(reg, FakeHebbian(), fallback_capability="llm_chat")
    with pytest.raises(ValueError, match="No agent found with the required capability"):
        router.route({"required_capability": "chitchat"})


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


# ---- Trust-aware routing ---------------------------------------------------


@pytest.mark.unit
def test_hebbian_router_beta_one_prefers_highest_trust():
    """At beta=1 (alpha=0) the trust signal alone decides — highest trust wins."""
    reg = _two_research_agents({"A": 0.9, "B": 0.6})  # A wins on composite
    trust = FakeTrust({"A": 0.2, "B": 0.95})  # but B is more trusted
    router = HebbianRouter(
        reg, FakeHebbian(), alpha=0.0, beta=1.0, trust_interface=trust
    )
    assert router.route_name({"required_capability": "research"}) == "B"


@pytest.mark.unit
def test_hebbian_router_trust_floor_excludes_low_trust_agent():
    """An agent below trust_floor is excluded even if its composite is best."""
    reg = _two_research_agents({"A": 0.95, "B": 0.5})
    trust = FakeTrust({"A": 0.1, "B": 0.9})  # A would win, but is below floor
    router = HebbianRouter(
        reg, FakeHebbian(), alpha=0.3, trust_interface=trust, trust_floor=0.5
    )
    decision = router.route({"required_capability": "research"})
    assert decision.agent_name == "B"
    assert {c.name for c in decision.candidates} == {"B"}  # A filtered out
    assert decision.trust_floor == 0.5


@pytest.mark.unit
def test_hebbian_router_with_no_trust_interface_is_backwards_compatible():
    """Omitting trust_interface preserves the legacy 2-signal blend exactly."""
    reg = _two_research_agents({"A": 0.9, "B": 0.6})
    heb = FakeHebbian({"A": 1.0, "B": 10.0})

    legacy = HebbianRouter(reg, heb, alpha=0.5)
    trust_disabled = HebbianRouter(reg, heb, alpha=0.5, trust_interface=None)

    d_legacy = legacy.route({"required_capability": "research"})
    d_new = trust_disabled.route({"required_capability": "research"})
    assert d_legacy.agent_name == d_new.agent_name
    # blended scores must match within float noise
    legacy_by = {c.name: c.blended for c in d_legacy.candidates}
    new_by = {c.name: c.blended for c in d_new.candidates}
    for name in legacy_by:
        assert abs(legacy_by[name] - new_by[name]) < 1e-9


@pytest.mark.unit
def test_hebbian_router_tolerates_broken_trust_source():
    """A trust source that raises falls back to the neutral prior, not a crash."""
    reg = _two_research_agents({"A": 0.9, "B": 0.6})
    trust = FakeTrust(raise_on={"A", "B"})  # every read raises
    router = HebbianRouter(
        reg, FakeHebbian(), alpha=0.0, beta=0.5, trust_interface=trust
    )
    # With both trust reads neutral and alpha=0, composite tie-broken on score:
    # A (0.9) beats B (0.6).
    assert router.route_name({"required_capability": "research"}) == "A"


@pytest.mark.unit
def test_hebbian_router_clamps_alpha_plus_beta_to_one():
    """alpha + beta > 1 silently clamps beta so the composite weight stays >= 0."""
    reg = _two_research_agents({"A": 0.9, "B": 0.6})
    router = HebbianRouter(reg, FakeHebbian(), alpha=0.8, beta=0.9)  # would sum to 1.7
    assert router.alpha == 0.8
    assert router.beta == pytest.approx(0.2)  # clamped to 1 - alpha


@pytest.mark.unit
def test_hebbian_router_trust_floor_with_no_survivors_raises():
    """A trust-floor-only denial reports the specific hard gate."""
    reg = _two_research_agents({"A": 0.9, "B": 0.6})
    trust = FakeTrust({"A": 0.1, "B": 0.1})
    router = HebbianRouter(reg, FakeHebbian(), trust_interface=trust, trust_floor=0.5)
    # Trust-floor exclusion has its own diagnostic so the operator can
    # tell "no agent below floor" apart from "no agent advertised the
    # capability" -- the two failure modes need different fixes.
    with pytest.raises(ValueError, match="below trust floor"):
        router.route({"required_capability": "research"})


@pytest.mark.unit
def test_hebbian_router_trust_floor_exclusion_does_not_silently_fall_back():
    """A trust-floor-only exclusion must not retry on fallback_capability.

    The fallback path is for "no agent advertised this capability". A
    trust-floor exclusion is a policy decision -- silently routing to the
    LLM agent's llm_chat would bypass the operator's trust requirement.
    """
    reg = FakeRegistry(
        [
            _Agent("Research", ["web_search"]),  # below floor
            _Agent("LLM", ["llm_chat"]),  # above floor
        ],
        {"Research": 0.9, "LLM": 0.5},
    )
    # Research advertises web_search (the requested capability) but its
    # trust is below floor. The LLM agent (which fallback would target)
    # is above floor, but should NOT be selected -- the user asked for
    # web_search subject to a trust requirement, and the trust failed.
    trust = FakeTrust({"Research": 0.1, "LLM": 0.9})
    router = HebbianRouter(
        reg,
        FakeHebbian(),
        trust_interface=trust,
        trust_floor=0.5,
        fallback_capability="llm_chat",
    )
    with pytest.raises(ValueError, match="below trust floor"):
        router.route({"required_capability": "web_search"})


@pytest.mark.unit
def test_hebbian_router_uses_atp_routing_scope_for_learning():
    reg = _two_research_agents({"A": 0.5, "B": 0.5})
    scope = "atp:reflect:research"
    heb = FakeHebbian(
        scoped_weights={("A", scope): 1.0, ("B", scope): 5.0},
    )
    router = HebbianRouter(reg, heb, alpha=1.0)

    decision = router.route(
        {
            "required_capability": "research",
            "routing_scope": scope,
            "atp_action_type": "Reflect",
        }
    )

    assert decision.agent_name == "B"
    assert decision.routing_scope == scope
    assert decision.atp_action_type == "Reflect"


@pytest.mark.unit
def test_hebbian_router_exposes_sentinel_without_changing_ranking():
    reg = _two_research_agents({"A": 0.9, "B": 0.6})
    heb = FakeHebbian(
        stability={
            ("A", "research"): {
                "oscillation_rate": 0.6,
                "alert_active": True,
                "sample_count": 50,
            }
        }
    )
    decision = HebbianRouter(reg, heb, alpha=0.0).route(
        {"required_capability": "research"}
    )

    assert decision.agent_name == "A"
    candidate = next(item for item in decision.candidates if item.name == "A")
    assert candidate.sentinel_alert is True
    assert candidate.oscillation_rate == pytest.approx(0.6)


@pytest.mark.unit
def test_hebbian_ranker_scores_only_the_already_eligible_tuple():
    """Learned evidence cannot discover or reintroduce an excluded agent."""
    hebbian = FakeHebbian(
        scoped_weights={
            ("eligible-agent", "llm_chat"): 1.0,
            ("quarantined-agent", "llm_chat"): 1000.0,
        }
    )
    ranker = HebbianRanker(hebbian, alpha=1.0)
    candidates = (
        EligibleCandidate(
            agent_id="agent:eligible-agent",
            name="eligible-agent",
            capabilities=frozenset({"llm_chat"}),
            composite_score=0.2,
            trust_score=0.8,
        ),
    )

    decision = ranker.rank(_authorized(), candidates)

    assert decision.agent_name == "eligible-agent"
    assert [candidate.name for candidate in decision.candidates] == ["eligible-agent"]


@pytest.mark.unit
def test_quarantined_high_score_never_reaches_production_ranker():
    """The eligibility-to-ranking handoff must exclude learned-score bypasses."""

    class RecordingHebbian(FakeHebbian):
        def __init__(self):
            super().__init__(
                scoped_weights={
                    ("eligible-agent", "llm_chat"): 1.0,
                    ("quarantined-agent", "llm_chat"): 1000.0,
                }
            )
            self.seen = []

        def get_task_type_weight(self, name, task_type):
            self.seen.append(name)
            return super().get_task_type_weight(name, task_type)

    authorized = _authorized()
    candidates = _filter(
        (
            _record("eligible-agent", composite_score=0.1),
            _record(
                "quarantined-agent",
                quarantined=True,
                composite_score=1.0,
            ),
        )
    ).candidates(authorized)
    hebbian = RecordingHebbian()

    decision = HebbianRanker(hebbian, alpha=1.0).rank(authorized, candidates)

    assert hebbian.seen == ["eligible-agent"]
    assert decision.agent_name == "eligible-agent"


@pytest.mark.unit
def test_hebbian_ranker_requires_an_immutable_candidate_tuple():
    """A mutable/list boundary could be altered between filtering and ranking."""
    ranker = HebbianRanker(FakeHebbian())
    candidate = EligibleCandidate(
        agent_id="agent:a",
        name="a",
        capabilities=frozenset({"llm_chat"}),
        composite_score=0.5,
        trust_score=0.8,
    )

    with pytest.raises(TypeError, match="tuple"):
        ranker.rank(_authorized(), [candidate])  # type: ignore[arg-type]


@pytest.mark.unit
def test_hebbian_ranker_breaks_exact_ties_by_name() -> None:
    """Changing input order must not change a tied production route."""
    ranker = HebbianRanker(FakeHebbian(), alpha=0.0, beta=0.0)
    candidates = tuple(
        EligibleCandidate(
            agent_id=f"agent:{name}",
            name=name,
            capabilities=frozenset({"llm_chat"}),
            composite_score=0.5,
            trust_score=0.8,
        )
        for name in ("z-agent", "a-agent")
    )

    decision = ranker.rank(_authorized(), candidates)

    assert decision.agent_name == "a-agent"


@pytest.mark.unit
def test_hebbian_ranker_has_no_fallback_or_discovery_path():
    """An empty eligible tuple must stop instead of selecting a fallback."""
    ranker = HebbianRanker(FakeHebbian(weights={"LLM": 1000.0}))

    with pytest.raises(ValueError, match="No eligible candidates"):
        ranker.rank(_authorized(), ())


@pytest.mark.unit
@pytest.mark.parametrize("field", ["alpha", "beta", "neutral_prior"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_hebbian_ranker_rejects_non_finite_configuration(
    field: str, value: float
) -> None:
    """Non-finite blend configuration cannot enter production ranking."""
    with pytest.raises(ValueError, match="finite"):
        HebbianRanker(FakeHebbian(), **{field: value})


@pytest.mark.unit
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_hebbian_ranker_neutralizes_non_finite_evidence_deterministically(
    bad_value: float,
) -> None:
    """Non-finite optional evidence is neutral under either candidate order."""

    class NonFiniteHebbian(FakeHebbian):
        def get_task_type_weight(self, name, task_type):
            return bad_value

        def has_task_type_history(self, name):
            return True

        def get_pair_bonus(self, name):
            return bad_value

        def get_timing_score(self, name, task_type):
            return bad_value

        def get_stability_signal(self, name, task_type):
            return {
                "oscillation_rate": bad_value,
                "alert_active": True,
                "sample_count": 1,
            }

    def candidates(order):
        return tuple(
            EligibleCandidate(
                agent_id=f"agent:{name}",
                name=name,
                capabilities=frozenset({"llm_chat"}),
                composite_score=0.5,
                trust_score=0.8,
            )
            for name in order
        )

    ranker = HebbianRanker(NonFiniteHebbian(), alpha=0.5, beta=0.25)
    forward = ranker.rank(_authorized(), candidates(("z-agent", "a-agent")))
    reverse = ranker.rank(_authorized(), candidates(("a-agent", "z-agent")))

    assert forward.agent_name == reverse.agent_name == "a-agent"
    for decision in (forward, reverse):
        for score in decision.candidates:
            assert all(
                isfinite(value)
                for value in (
                    score.hebbian_weight,
                    score.hebbian_norm,
                    score.pair_bonus,
                    score.hebbian_effective,
                    score.oscillation_rate,
                    score.blended,
                )
            )
            assert score.hebbian_weight == 0.0
            assert score.pair_bonus == 0.0
            assert score.timing_score is None
            assert score.oscillation_rate == 0.0
