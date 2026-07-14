"""Integration tests for write-through learning/governance coordination."""

import pytest

from src.agents.base_agent import BaseAgent
from src.governance.checkpoints import CheckpointStore
from src.integration.agent_registry import AgentRegistry
from src.integration.learning_governance import LearningGovernanceCoordinator
from src.integration.trust_interface import TrustInterface
from src.mcp.hebbian_weights import HebbianWeightManager


class _Agent(BaseAgent):
    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success", "summary": "ok"}


@pytest.fixture
def coordinated_state(tmp_path):
    registry = AgentRegistry(db_path=str(tmp_path / "agent_registry.db"))
    registry.register_agent(_Agent("Alpha", capabilities=["research"]))
    trust = TrustInterface(db_path=tmp_path / "trust_scores.db")
    hebbian = HebbianWeightManager(db_path=str(tmp_path / "hebbian_weights.db"))
    checkpoints = CheckpointStore(checkpoint_dir=str(tmp_path / "checkpoints"))
    coordinator = LearningGovernanceCoordinator(
        registry,
        trust_interface=trust,
        hebbian_manager=hebbian,
        checkpoint_store=checkpoints,
    )
    coordinator.reconcile_agent("Alpha")
    return registry, trust, hebbian, checkpoints, coordinator


def test_execution_updates_hebbian_registry_and_trust_projection(coordinated_state):
    registry, trust, hebbian, _checkpoints, coordinator = coordinated_state
    learning = hebbian.record_outcome(
        "Alpha",
        "T1",
        success=True,
        performance=0.9,
        task_type="research",
    )

    metrics = coordinator.record_execution_outcome(
        "Alpha",
        success=True,
        learning=learning,
    )

    record = registry.store.get_agent_record("Alpha")
    assert record["execution_count"] == 1
    assert record["hebbian_weight"] == pytest.approx(learning["weight"])
    assert trust.get_trust_score("Alpha").score == pytest.approx(metrics["trust_score"])


def test_violation_updates_both_trust_stores_but_not_hebbian(coordinated_state):
    registry, trust, hebbian, checkpoints, coordinator = coordinated_state
    before = hebbian.get_network_summary()["total_connections"]

    result = coordinator.record_violation("Alpha", "rate_limit", {"source": "test"})

    assert registry.get_governance_state("Alpha")["trust_score"] == pytest.approx(
        result["trust_score"]
    )
    assert trust.get_trust_score("Alpha").score == pytest.approx(result["trust_score"])
    assert hebbian.get_network_summary()["total_connections"] == before
    assert len(checkpoints.list_checkpoints()) == 1


def test_manual_trust_adjustment_is_mirrored_to_registry(coordinated_state):
    registry, _trust, _hebbian, _checkpoints, coordinator = coordinated_state

    updated = coordinator.record_trust_adjustment(
        "Alpha",
        success=False,
        amount=0.1,
    )

    assert registry.get_governance_state("Alpha")["trust_score"] == pytest.approx(
        updated.score
    )
