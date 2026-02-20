"""
Tests for Hebbian learning implementation.
"""

import os
import tempfile
from unittest.mock import MagicMock

import pytest
from mcp.hebbian_weights import HebbianWeightManager


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db") as f:
        db_path = f.name

    yield db_path

    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def hebbian_manager(temp_db):
    """Create a HebbianWeightManager instance with temp database."""
    return HebbianWeightManager(db_path=temp_db)


class TestHebbianWeightManager:
    """Test suite for Hebbian weight management."""

    def test_initialization(self, hebbian_manager):
        """Test that the manager initializes correctly."""
        assert hebbian_manager is not None
        summary = hebbian_manager.get_network_summary()
        assert summary["total_connections"] == 0

    def test_strengthen_connection_new(self, hebbian_manager):
        """Test strengthening a new connection."""
        weight = hebbian_manager.strengthen_connection("agent_a", "task_1")
        assert weight == 1.0

    def test_strengthen_connection_existing(self, hebbian_manager):
        """Test strengthening an existing connection."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        weight = hebbian_manager.strengthen_connection("agent_a", "task_1")
        assert weight == 2.0

    def test_weaken_connection_new(self, hebbian_manager):
        """Test weakening a non-existent connection (should create it at 0)."""
        weight = hebbian_manager.weaken_connection("agent_a", "task_1")
        assert weight == 0.0

    def test_weaken_connection_existing(self, hebbian_manager):
        """Test weakening an existing connection."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        weight = hebbian_manager.weaken_connection("agent_a", "task_1")
        assert weight == 1.0

    def test_weaken_connection_minimum_zero(self, hebbian_manager):
        """Test that weights don't go below zero."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.weaken_connection("agent_a", "task_1")
        weight = hebbian_manager.weaken_connection("agent_a", "task_1")
        assert weight == 0.0

    def test_get_weight(self, hebbian_manager):
        """Test getting connection weight."""
        assert hebbian_manager.get_weight("agent_a", "task_1") == 0.0
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        assert hebbian_manager.get_weight("agent_a", "task_1") == 1.0

    def test_get_connection_stats(self, hebbian_manager):
        """Test getting detailed connection statistics."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        stats = hebbian_manager.get_connection_stats("agent_a", "task_1")

        assert stats is not None
        assert stats["weight"] == 1.0
        assert stats["activation_count"] == 1
        assert stats["success_count"] == 1
        assert stats["failure_count"] == 0

    def test_get_strongest_connections_outgoing(self, hebbian_manager):
        """Test getting strongest outgoing connections."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_2")

        connections = hebbian_manager.get_strongest_connections("agent_a", limit=10)

        assert len(connections) == 2
        assert connections[0] == ("task_1", 2.0)
        assert connections[1] == ("task_2", 1.0)

    def test_get_strongest_connections_incoming(self, hebbian_manager):
        """Test getting strongest incoming connections."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_b", "task_1")
        hebbian_manager.strengthen_connection("agent_b", "task_1")

        connections = hebbian_manager.get_strongest_connections(
            "task_1", limit=10, direction="incoming"
        )

        assert len(connections) == 2
        assert connections[0] == ("agent_b", 2.0)
        assert connections[1] == ("agent_a", 1.0)

    def test_get_agent_average_weight(self, hebbian_manager):
        """Test calculating agent average weight."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_2")

        avg_weight = hebbian_manager.get_agent_average_weight("agent_a")
        assert avg_weight == 1.5  # (2.0 + 1.0) / 2

    def test_get_agent_success_rate(self, hebbian_manager):
        """Test calculating agent success rate."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_2")
        hebbian_manager.weaken_connection("agent_a", "task_3")

        success_rate = hebbian_manager.get_agent_success_rate("agent_a")
        assert success_rate == 2.0 / 3.0  # 2 successes out of 3 activations

    def test_get_network_summary(self, hebbian_manager):
        """Test getting network summary statistics."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_b", "task_2")
        hebbian_manager.weaken_connection("agent_c", "task_3")

        summary = hebbian_manager.get_network_summary()

        assert summary["total_connections"] == 3
        assert summary["total_activations"] == 3
        assert summary["total_successes"] == 2
        assert summary["total_failures"] == 1
        assert summary["success_rate"] == 2.0 / 3.0

    def test_prune_weak_connections(self, hebbian_manager):
        """Test pruning connections below threshold."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_b", "task_2")
        hebbian_manager.weaken_connection("agent_c", "task_3")

        pruned = hebbian_manager.prune_weak_connections(threshold=0.5)

        assert pruned == 1  # Only agent_c -> task_3 (weight 0) should be pruned
        assert hebbian_manager.get_weight("agent_a", "task_1") == 2.0
        assert hebbian_manager.get_weight("agent_b", "task_2") == 1.0
        assert hebbian_manager.get_weight("agent_c", "task_3") == 0.0  # Pruned

    def test_reset_weights(self, hebbian_manager):
        """Test resetting all weights."""
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_b", "task_2")

        hebbian_manager.reset_weights()

        summary = hebbian_manager.get_network_summary()
        assert summary["total_connections"] == 0

    def test_multiple_activations_tracking(self, hebbian_manager):
        """Test that activation counts are tracked correctly."""
        # Multiple successes
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_1")

        # Some failures
        hebbian_manager.weaken_connection("agent_a", "task_1")

        stats = hebbian_manager.get_connection_stats("agent_a", "task_1")

        assert stats["activation_count"] == 4
        assert stats["success_count"] == 3
        assert stats["failure_count"] == 1
        assert stats["weight"] == 2.0  # 3 successes - 1 failure


@pytest.mark.integration
class TestHebbianIntegration:
    """Integration tests for Hebbian learning in the orchestrator."""

    @pytest.fixture(autouse=True)
    def temp_obsidian_vault(self, tmp_path, monkeypatch):
        """Isolate orchestrator tests from real vault by using a temp directory."""
        temp_vault = tmp_path / "obsidian_vault"
        temp_vault.mkdir(parents=True, exist_ok=True)

        # Patch both config and orchestrator module constants before instantiation
        import mcp.config as config

        monkeypatch.setattr(config, "OBSIDIAN_VAULT_PATH", str(temp_vault))
        import mcp.orchestrator as orchestrator_module

        monkeypatch.setattr(orchestrator_module, "OBSIDIAN_VAULT_PATH", str(temp_vault))
        monkeypatch.setattr(
            orchestrator_module,
            "LocalVectorStore",
            lambda: MagicMock(count=lambda: 0),
        )
        monkeypatch.setattr(
            orchestrator_module,
            "MemoryBus",
            lambda *args, **kwargs: MagicMock(
                write_note_with_embedding=lambda *a, **k: {"status": "success"},
                read=lambda *a, **k: [],
            ),
        )

        yield

    def test_orchestrator_creates_hebbian_manager(self):
        """Test that orchestrator initializes with Hebbian manager."""
        from mcp.orchestrator import Orchestrator

        orchestrator = Orchestrator()
        assert orchestrator.hebbian is not None
        assert isinstance(orchestrator.hebbian, HebbianWeightManager)

    def test_orchestrator_updates_weights_on_success(self):
        """Test that successful tasks strengthen connections."""
        from src.mcp.orchestrator import Orchestrator

        orchestrator = Orchestrator()

        # Get initial weight
        initial_weight = orchestrator.hebbian.get_weight(
            "Artemis Agent", "test_task_123"
        )

        # Create a simple task
        task_context = {
            "task_id": "test_task_123",
            "title": "Test Task",
            "content": "Test content",
        }

        # Execute task
        try:
            orchestrator.assign_and_execute_task("Artemis Agent", task_context)
        except Exception:
            pass  # Task might fail, but weight should still update

        # Check that weight increased
        final_weight = orchestrator.hebbian.get_weight("Artemis Agent", "test_task_123")
        assert final_weight > initial_weight
