"""
Tests for Hebbian learning implementation.
"""

import copy
import math
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from src.mcp.hebbian_weights import HebbianWeightManager


@pytest.fixture
def temp_db():
    """Create a temporary database for testing.

    Returns:
        None: This function does not return a value.
    """
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db") as f:
        db_path = f.name

    yield db_path

    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def hebbian_manager(temp_db):
    """Create a HebbianWeightManager instance with temp database.

    Args:
        temp_db: Temp db value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    return HebbianWeightManager(db_path=temp_db)


class TestHebbianWeightManager:
    """Test suite for Hebbian weight management."""

    def test_initialization(self, hebbian_manager):
        """Test that the manager initializes correctly.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert hebbian_manager is not None
        summary = hebbian_manager.get_network_summary()
        assert summary["total_connections"] == 0

    def test_record_outcome_uses_nonlinear_simulation_rule(self, hebbian_manager):
        """Runtime success uses tanh reinforcement, decay, and scoped storage."""
        update = hebbian_manager.record_outcome(
            "agent_a",
            "task_1",
            success=True,
            performance=0.8,
            task_type="research",
            duration_ms=25.0,
        )

        expected_delta = math.tanh(0.1 * 0.8)
        expected_weight = (1.0 + expected_delta) * 0.99
        assert update["delta"] == pytest.approx(expected_delta)
        assert update["weight"] == pytest.approx(expected_weight)
        assert hebbian_manager.get_weight("agent_a", "task_1") == pytest.approx(
            expected_weight
        )
        assert hebbian_manager.get_task_type_weight(
            "agent_a", "research"
        ) == pytest.approx(expected_weight)

    def test_record_outcome_applies_anti_hebbian_update_and_global_decay(
        self, hebbian_manager
    ):
        """A failed run penalizes its edge and decays prior connections once."""
        first = hebbian_manager.record_outcome(
            "agent_a",
            "task_1",
            success=True,
            performance=1.0,
            task_type="research",
        )
        failed = hebbian_manager.record_outcome(
            "agent_b",
            "task_2",
            success=False,
            performance=0.0,
            task_type="research",
        )

        assert failed["delta"] == pytest.approx(-0.1)
        assert failed["weight"] == pytest.approx((1.0 - 0.1) * 0.99)
        assert hebbian_manager.get_weight("agent_a", "task_1") == pytest.approx(
            first["weight"] * 0.99
        )

    def test_record_outcome_persists_pair_timing_and_compounding_signals(
        self, hebbian_manager
    ):
        """Sequential and rolling subsystems from the full simulation are live."""
        hebbian_manager.record_outcome(
            "agent_a",
            "task_a",
            success=True,
            performance=0.9,
            task_type="research",
            duration_ms=100,
        )
        update = hebbian_manager.record_outcome(
            "agent_b",
            "task_b",
            success=True,
            performance=0.8,
            task_type="research",
            duration_ms=80,
        )
        for index in range(4):
            update = hebbian_manager.record_outcome(
                "agent_b",
                f"task_b_{index}",
                success=True,
                performance=0.8,
                task_type="research",
                duration_ms=80,
            )

        assert update["pair_information"] > 0
        assert hebbian_manager.get_timing_score("agent_b", "research") == pytest.approx(
            0.8
        )
        compounding = hebbian_manager.get_compounding_value()
        assert compounding["routing_intelligence"] >= compounding["pair_information"]

    def test_strengthen_connection_new(self, hebbian_manager):
        """Test strengthening a new connection.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        weight = hebbian_manager.strengthen_connection("agent_a", "task_1")
        assert weight == 1.0

    def test_strengthen_connection_existing(self, hebbian_manager):
        """Test strengthening an existing connection.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        weight = hebbian_manager.strengthen_connection("agent_a", "task_1")
        assert weight == 2.0

    def test_weaken_connection_new(self, hebbian_manager):
        """Test weakening a non-existent connection (should create it at 0).

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        weight = hebbian_manager.weaken_connection("agent_a", "task_1")
        assert weight == 0.0

    def test_weaken_connection_existing(self, hebbian_manager):
        """Test weakening an existing connection.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        weight = hebbian_manager.weaken_connection("agent_a", "task_1")
        assert weight == 1.0

    def test_weaken_connection_minimum_zero(self, hebbian_manager):
        """Test that weights don't go below zero.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.weaken_connection("agent_a", "task_1")
        weight = hebbian_manager.weaken_connection("agent_a", "task_1")
        assert weight == 0.0

    def test_get_weight(self, hebbian_manager):
        """Test getting connection weight.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        assert hebbian_manager.get_weight("agent_a", "task_1") == 0.0
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        assert hebbian_manager.get_weight("agent_a", "task_1") == 1.0

    def test_get_connection_stats(self, hebbian_manager):
        """Test getting detailed connection statistics.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        stats = hebbian_manager.get_connection_stats("agent_a", "task_1")

        assert stats is not None
        assert stats["weight"] == 1.0
        assert stats["activation_count"] == 1
        assert stats["success_count"] == 1
        assert stats["failure_count"] == 0

    def test_get_strongest_connections_outgoing(self, hebbian_manager):
        """Test getting strongest outgoing connections.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_2")

        connections = hebbian_manager.get_strongest_connections("agent_a", limit=10)

        assert len(connections) == 2
        assert connections[0] == ("task_1", 2.0)
        assert connections[1] == ("task_2", 1.0)

    def test_get_strongest_connections_incoming(self, hebbian_manager):
        """Test getting strongest incoming connections.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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
        """Test calculating agent average weight.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_2")

        avg_weight = hebbian_manager.get_agent_average_weight("agent_a")
        assert avg_weight == 1.5  # (2.0 + 1.0) / 2

    def test_task_type_weight_distinguishes_cold_start_from_zero(self, hebbian_manager):
        """A missing scope is None while a learned failure remains 0.0."""
        assert hebbian_manager.get_task_type_weight("agent_a", "research") is None

        hebbian_manager.weaken_task_type("agent_a", "research")

        assert hebbian_manager.get_task_type_weight("agent_a", "research") == 0.0

    def test_task_type_weight_learns_independently_per_capability(
        self, hebbian_manager
    ):
        """Success in one capability does not inflate another capability."""
        hebbian_manager.strengthen_task_type("agent_a", "research")
        hebbian_manager.strengthen_task_type("agent_a", "research")
        hebbian_manager.strengthen_task_type("agent_a", "summarization")

        assert hebbian_manager.get_task_type_weight("agent_a", "research") == 2.0
        assert hebbian_manager.get_task_type_weight("agent_a", "summarization") == 1.0
        assert hebbian_manager.has_task_type_history("agent_a") is True
        assert hebbian_manager.has_task_type_history("agent_b") is False

    def test_get_agent_success_rate(self, hebbian_manager):
        """Test calculating agent success rate.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_a", "task_2")
        hebbian_manager.weaken_connection("agent_a", "task_3")

        success_rate = hebbian_manager.get_agent_success_rate("agent_a")
        assert success_rate == 2.0 / 3.0  # 2 successes out of 3 activations

    def test_get_network_summary(self, hebbian_manager):
        """Test getting network summary statistics.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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
        """Test pruning connections below threshold.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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
        """Test resetting all weights.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        hebbian_manager.strengthen_connection("agent_a", "task_1")
        hebbian_manager.strengthen_connection("agent_b", "task_2")

        hebbian_manager.reset_weights()

        summary = hebbian_manager.get_network_summary()
        assert summary["total_connections"] == 0

    def test_multiple_activations_tracking(self, hebbian_manager):
        """Test that activation counts are tracked correctly.

        Args:
            hebbian_manager: Hebbian manager value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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


def test_hebbian_sentinel_detects_and_resolves_oscillation(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTEMIS_HEBBIAN_SENTINEL_WINDOW", "4")
    monkeypatch.setenv("ARTEMIS_HEBBIAN_SENTINEL_WARMUP", "4")
    monkeypatch.setenv("ARTEMIS_HEBBIAN_SENTINEL_THRESHOLD", "0.4")
    manager = HebbianWeightManager(db_path=str(tmp_path / "sentinel.db"))

    latest = None
    for index, success in enumerate((True, False, True, False)):
        latest = manager.record_outcome(
            "agent_a",
            f"oscillating-{index}",
            success=success,
            performance=1.0 if success else 0.0,
            task_type="atp:execute:llm_chat",
        )

    assert latest is not None
    assert latest["sentinel_alert"] is True
    assert latest["oscillation_rate"] == pytest.approx(0.75)
    assert manager.list_sentinel_alerts(open_only=True)[0]["status"] == "open"

    for index in range(4):
        latest = manager.record_outcome(
            "agent_a",
            f"stable-{index}",
            success=True,
            performance=1.0,
            task_type="atp:execute:llm_chat",
        )

    assert latest["sentinel_alert"] is False
    assert latest["oscillation_rate"] == 0.0
    assert manager.list_sentinel_alerts(open_only=True) == []
    assert manager.list_sentinel_alerts()[0]["status"] == "resolved"


def test_hebbian_snapshot_includes_sentinel_tables(hebbian_manager):
    snapshot = hebbian_manager.export_snapshot()
    assert "hebbian_sentinel_state" in snapshot["tables"]
    assert "hebbian_sentinel_alerts" in snapshot["tables"]


def test_hebbian_snapshot_restores_legacy_partial_rows(hebbian_manager):
    snapshot = {
        "schema_version": 1,
        "tables": {
            "node_connections": [
                {"origin_node": "legacy-agent", "target_node": "legacy-task"}
            ]
        },
    }

    restored = hebbian_manager.restore_snapshot(snapshot)

    assert restored["node_connections"] == 1
    connection = hebbian_manager.get_connection_stats("legacy-agent", "legacy-task")
    assert connection is not None
    assert connection["weight"] == 0.0
    assert connection["activation_count"] == 0
    assert connection["last_delta"] == 0.0
    assert connection["last_performance"] == 0.0
    assert hebbian_manager.export_snapshot()["tables"]["hebbian_engine_state"] == [
        {
            "singleton": 1,
            "last_agent": None,
            "last_performance": None,
            "updated_at": None,
        }
    ]


def test_hebbian_snapshot_rejects_unknown_columns_atomically(hebbian_manager):
    hebbian_manager.strengthen_connection("agent", "task")
    before = copy.deepcopy(hebbian_manager.export_snapshot())
    invalid = copy.deepcopy(before)
    invalid["tables"]["node_connections"][0]["unsafe,column"] = "blocked"

    with pytest.raises(ValueError, match="unknown columns"):
        hebbian_manager.restore_snapshot(invalid)

    assert hebbian_manager.export_snapshot() == before


@pytest.mark.integration
class TestHebbianIntegration:
    """Integration tests for Hebbian learning in the orchestrator."""

    @pytest.fixture(autouse=True)
    def temp_obsidian_vault(self, tmp_path, monkeypatch):
        """Isolate orchestrator tests from real vault by using a temp directory.

        Args:
            tmp_path: Tmp path value used by this operation.
            monkeypatch: Monkeypatch value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        temp_vault = tmp_path / "obsidian_vault"
        temp_vault.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("ARTEMIS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("ARTEMIS_LOG_DIR", str(tmp_path / "logs"))

        # Patch both config and orchestrator module constants before instantiation
        import src.mcp.config as config

        monkeypatch.setattr(config, "OBSIDIAN_VAULT_PATH", str(temp_vault))
        import src.mcp.orchestrator as orchestrator_module

        monkeypatch.setattr(orchestrator_module, "OBSIDIAN_VAULT_PATH", str(temp_vault))
        # AGENT_INPUT_DIR / AGENT_OUTPUT_DIR default to absolute paths from
        # the original author's machine; rebind to vault-relative names so
        # ObsidianManager.create_folder lands inside the tmp vault.
        monkeypatch.setattr(orchestrator_module, "AGENT_INPUT_DIR", "Agent Inputs")
        monkeypatch.setattr(orchestrator_module, "AGENT_OUTPUT_DIR", "Agent Outputs")
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
        """Test that orchestrator initializes with Hebbian manager.

        Returns:
            None: This function does not return a value.
        """
        import src.mcp.orchestrator as orchestrator_module

        orchestrator = orchestrator_module.Orchestrator()
        assert orchestrator.hebbian is not None
        assert isinstance(orchestrator.hebbian, HebbianWeightManager)

    def test_orchestrator_updates_weights_on_success(self):
        """Test that successful tasks strengthen connections.

        Returns:
            None: This function does not return a value.
        """
        import src.mcp.orchestrator as orchestrator_module

        orchestrator = orchestrator_module.Orchestrator()
        artemis = orchestrator.agent_registry.get_agent("Artemis Agent")
        artemis.perform_task = MagicMock(
            return_value={
                "status": "success",
                "summary": "measured success",
                "outcome_class": "success",
                "learning_eligible": True,
            }
        )

        # Get initial weight
        initial_weight = orchestrator.hebbian.get_weight(
            "Artemis Agent", "test_task_123"
        )

        # Create a simple task
        task_context = {
            "task_id": "test_task_123",
            "title": "Test Task",
            "content": "Test content",
            "disable_llm_delegate": True,
        }

        # Execute a deterministic measured success. Provider outages are
        # intentionally excluded from learning and belong in separate tests.
        orchestrator.assign_and_execute_task("Artemis Agent", task_context)

        # Check that weight increased
        final_weight = orchestrator.hebbian.get_weight("Artemis Agent", "test_task_123")
        assert final_weight > initial_weight
