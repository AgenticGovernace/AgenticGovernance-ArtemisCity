"""Tests for the agent registry (src/integration/agent_registry.py)."""

import sys

sys.modules.pop("integration.agent_registry", None)

import pytest
from agents.base_agent import BaseAgent
from integration.agent_registry import AgentRegistry, AgentRegistryStore, AgentScore


# ---------------------------------------------------------------------------
# Concrete agent for testing
# ---------------------------------------------------------------------------
class _StubAgent(BaseAgent):
    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success", "summary": "stub"}


# ---------------------------------------------------------------------------
# AgentScore
# ---------------------------------------------------------------------------
class TestAgentScore:
    def test_composite_score(self):
        s = AgentScore(alignment=1.0, accuracy=1.0, efficiency=1.0)
        assert s.composite_score == 1.0

    def test_composite_score_weighted(self):
        s = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
        expected = 0.5 * 0.4 + 0.5 * 0.4 + 0.5 * 0.2
        assert abs(s.composite_score - expected) < 0.001

    def test_composite_score_zeros(self):
        s = AgentScore(alignment=0.0, accuracy=0.0, efficiency=0.0)
        assert s.composite_score == 0.0


# ---------------------------------------------------------------------------
# AgentRegistryStore (file-based SQLite via tmp_path)
# ---------------------------------------------------------------------------
class TestAgentRegistryStore:
    @pytest.fixture
    def store(self, tmp_path):
        return AgentRegistryStore(db_path=str(tmp_path / "registry.db"))

    def test_load_scores_empty(self, store):
        assert store.load_scores() == {}

    def test_upsert_and_load(self, store):
        agent = _StubAgent("Alpha", capabilities=["research"])
        default = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
        store.upsert_agent(agent, default)
        scores = store.load_scores()
        assert "Alpha" in scores
        assert abs(scores["Alpha"].alignment - 0.5) < 0.001

    def test_upsert_existing_preserves_scores(self, store):
        agent = _StubAgent("Alpha", capabilities=["research"])
        default = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
        store.upsert_agent(agent, default)
        new_default = AgentScore(alignment=0.9, accuracy=0.9, efficiency=0.9)
        returned = store.upsert_agent(agent, new_default)
        assert abs(returned.alignment - 0.5) < 0.001

    def test_update_score(self, store):
        agent = _StubAgent("Alpha", capabilities=["research"])
        default = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
        store.upsert_agent(agent, default)
        new_score = AgentScore(alignment=0.9, accuracy=0.8, efficiency=0.7)
        store.update_score("Alpha", new_score)
        scores = store.load_scores()
        assert abs(scores["Alpha"].alignment - 0.9) < 0.001


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------
class TestAgentRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        return AgentRegistry(db_path=str(tmp_path / "registry.db"))

    def test_register_and_get(self, registry):
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        assert registry.get_agent("Alpha") is agent

    def test_get_nonexistent(self, registry):
        assert registry.get_agent("ghost") is None

    def test_duplicate_registration(self, registry):
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        registry.register_agent(agent)
        assert len(registry.agents) == 1

    def test_route_task(self, registry):
        a1 = _StubAgent("Alpha", capabilities=["research"])
        a2 = _StubAgent("Beta", capabilities=["research", "code"])
        registry.register_agent(a1)
        registry.register_agent(a2)
        best = registry.route_task({"required_capability": "research"})
        assert best in ("Alpha", "Beta")

    def test_route_task_picks_highest_score(self, registry):
        a1 = _StubAgent("Alpha", capabilities=["research"])
        a2 = _StubAgent("Beta", capabilities=["research"])
        registry.register_agent(a1)
        registry.register_agent(a2)
        registry.scores["Beta"] = AgentScore(
            alignment=1.0, accuracy=1.0, efficiency=1.0
        )
        best = registry.route_task({"required_capability": "research"})
        assert best == "Beta"

    def test_route_task_no_capability_raises(self, registry):
        with pytest.raises(ValueError, match="required_capability"):
            registry.route_task({})

    def test_route_task_no_capable_agent_raises(self, registry):
        a1 = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(a1)
        with pytest.raises(ValueError, match="No agent found"):
            registry.route_task({"required_capability": "flying"})

    def test_update_score_dimension(self, registry):
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        old = registry.scores["Alpha"].alignment
        registry.update_score("Alpha", "alignment", 0.2)
        new = registry.scores["Alpha"].alignment
        assert abs(new - (old + 0.2)) < 0.001

    def test_update_score_clamps_to_one(self, registry):
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        registry.update_score("Alpha", "alignment", 2.0)
        assert registry.scores["Alpha"].alignment <= 1.0

    def test_update_score_clamps_to_zero(self, registry):
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        registry.update_score("Alpha", "alignment", -2.0)
        assert registry.scores["Alpha"].alignment >= 0.0

    def test_update_score_unknown_agent(self, registry):
        registry.update_score("ghost", "alignment", 0.1)

    def test_get_all_agents(self, registry):
        a1 = _StubAgent("Alpha", capabilities=["research"])
        a2 = _StubAgent("Beta", capabilities=["code"])
        registry.register_agent(a1)
        registry.register_agent(a2)
        assert len(registry.get_all_agents()) == 2

    def test_get_agent_names(self, registry):
        a1 = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(a1)
        assert registry.get_agent_names() == ["Alpha"]

    def test_get_all_agents_with_scores(self, registry):
        a1 = _StubAgent("Alpha", capabilities=["research"])
        a2 = _StubAgent("Beta", capabilities=["code"])
        registry.register_agent(a1)
        registry.register_agent(a2)
        registry.scores["Beta"] = AgentScore(
            alignment=1.0, accuracy=1.0, efficiency=1.0
        )
        result = registry.get_all_agents_with_scores()
        assert len(result) == 2
        assert result[0]["name"] == "Beta"
        assert result[0]["composite_score"] == 1.0
        assert "capabilities" in result[0]
