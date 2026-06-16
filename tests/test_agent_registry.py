"""Tests for the agent registry (src/integration/agent_registry.py)."""

import sys

sys.modules.pop("src.integration.agent_registry", None)

import pytest

from src.agents.base_agent import BaseAgent
from src.integration.agent_registry import AgentRegistry, AgentRegistryStore, AgentScore


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
    """Provide the TestAgentScore abstraction used by this module."""

    def test_composite_score(self):
        """Test that composite score.

        Returns:
            None: This function does not return a value.
        """
        s = AgentScore(alignment=1.0, accuracy=1.0, efficiency=1.0)
        assert s.composite_score == 1.0

    def test_composite_score_weighted(self):
        """Test that composite score weighted.

        Returns:
            None: This function does not return a value.
        """
        s = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
        expected = 0.5 * 0.4 + 0.5 * 0.4 + 0.5 * 0.2
        assert abs(s.composite_score - expected) < 0.001

    def test_composite_score_zeros(self):
        """Test that composite score zeros.

        Returns:
            None: This function does not return a value.
        """
        s = AgentScore(alignment=0.0, accuracy=0.0, efficiency=0.0)
        assert s.composite_score == 0.0


# ---------------------------------------------------------------------------
# AgentRegistryStore (file-based SQLite via tmp_path)
# ---------------------------------------------------------------------------
class TestAgentRegistryStore:
    """Persist and retrieve records for the TestAgentRegistryStore workflow."""

    @pytest.fixture
    def store(self, tmp_path):
        """Store.

        Args:
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        return AgentRegistryStore(db_path=str(tmp_path / "registry.db"))

    def test_load_scores_empty(self, store):
        """Test that load scores empty.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        assert store.load_scores() == {}

    def test_upsert_and_load(self, store):
        """Test that upsert and load.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        agent = _StubAgent("Alpha", capabilities=["research"])
        default = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
        store.upsert_agent(agent, default)
        scores = store.load_scores()
        assert "Alpha" in scores
        assert abs(scores["Alpha"].alignment - 0.5) < 0.001

    def test_upsert_existing_preserves_scores(self, store):
        """Test that upsert existing preserves scores.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        agent = _StubAgent("Alpha", capabilities=["research"])
        default = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
        store.upsert_agent(agent, default)
        new_default = AgentScore(alignment=0.9, accuracy=0.9, efficiency=0.9)
        returned = store.upsert_agent(agent, new_default)
        assert abs(returned.alignment - 0.5) < 0.001

    def test_update_score(self, store):
        """Test that update score.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
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
    """Provide the TestAgentRegistry abstraction used by this module."""

    @pytest.fixture
    def registry(self, tmp_path):
        """Registry.

        Args:
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        return AgentRegistry(db_path=str(tmp_path / "registry.db"))

    def test_register_and_get(self, registry):
        """Test that register and get.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        assert registry.get_agent("Alpha") is agent

    def test_get_nonexistent(self, registry):
        """Test that get nonexistent.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        assert registry.get_agent("ghost") is None

    def test_duplicate_registration(self, registry):
        """Test that duplicate registration.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        registry.register_agent(agent)
        assert len(registry.agents) == 1

    def test_route_task(self, registry):
        """Test that route task.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        a1 = _StubAgent("Alpha", capabilities=["research"])
        a2 = _StubAgent("Beta", capabilities=["research", "code"])
        registry.register_agent(a1)
        registry.register_agent(a2)
        best = registry.route_task({"required_capability": "research"})
        assert best in ("Alpha", "Beta")

    def test_route_task_picks_highest_score(self, registry):
        """Test that route task picks highest score.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
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
        """Test that route task no capability raises.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(ValueError, match="required_capability"):
            registry.route_task({})

    def test_route_task_no_capable_agent_raises(self, registry):
        """Test that route task no capable agent raises.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        a1 = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(a1)
        with pytest.raises(ValueError, match="No agent found"):
            registry.route_task({"required_capability": "flying"})

    def test_update_score_dimension(self, registry):
        """Test that update score dimension.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        old = registry.scores["Alpha"].alignment
        registry.update_score("Alpha", "alignment", 0.2)
        new = registry.scores["Alpha"].alignment
        assert abs(new - (old + 0.2)) < 0.001

    def test_update_score_clamps_to_one(self, registry):
        """Test that update score clamps to one.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        registry.update_score("Alpha", "alignment", 2.0)
        assert registry.scores["Alpha"].alignment <= 1.0

    def test_update_score_clamps_to_zero(self, registry):
        """Test that update score clamps to zero.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        agent = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(agent)
        registry.update_score("Alpha", "alignment", -2.0)
        assert registry.scores["Alpha"].alignment >= 0.0

    def test_update_score_unknown_agent(self, registry):
        """Test that update score unknown agent.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        registry.update_score("ghost", "alignment", 0.1)

    def test_get_all_agents(self, registry):
        """Test that get all agents.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        a1 = _StubAgent("Alpha", capabilities=["research"])
        a2 = _StubAgent("Beta", capabilities=["code"])
        registry.register_agent(a1)
        registry.register_agent(a2)
        assert len(registry.get_all_agents()) == 2

    def test_get_agent_names(self, registry):
        """Test that get agent names.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
        a1 = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(a1)
        assert registry.get_agent_names() == ["Alpha"]

    def test_get_all_agents_with_scores(self, registry):
        """Test that get all agents with scores.

        Args:
            registry: Agent registry used to persist and read governance state.

        Returns:
            None: This function does not return a value.
        """
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
