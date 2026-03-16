"""Integration tests for memory decay functionality."""

import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parents[2] / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
else:
    sys.path.remove(_src)
    sys.path.insert(0, _src)
for _key in [
    k for k in sys.modules if k == "integration" or k.startswith("integration.")
]:
    del sys.modules[_key]

from datetime import datetime, timedelta

import pytest

from integration.memory_decay import DecayEvent, MemoryDecayService, MemoryNode


class TestMemoryNode:
    """Tests for MemoryNode class."""

    def test_node_initialization(self):
        """Test memory node is initialized correctly."""
        node = MemoryNode(node_id="mem_1", weight=0.8)
        assert node.id == "mem_1"
        assert node.weight == 0.8
        assert node.archived is False

    def test_node_defaults(self):
        """Test memory node default values."""
        node = MemoryNode(node_id="mem_2")
        assert node.weight == 1.0
        assert node.archived is False
        assert isinstance(node.last_access, datetime)
        assert isinstance(node.created_at, datetime)

    def test_node_to_dict(self):
        """Test serialization."""
        node = MemoryNode(node_id="mem_3", weight=0.5)
        d = node.to_dict()
        assert d["id"] == "mem_3"
        assert d["weight"] == 0.5
        assert d["archived"] is False


class TestDecayEvent:
    """Tests for DecayEvent class."""

    def test_event_creation(self):
        """Test creating a decay event."""
        event = DecayEvent(
            node_id="n1",
            event_type="decay",
            previous_weight=1.0,
            new_weight=0.95,
            days_unused=30,
            reason="unused_30_days",
        )
        assert event.node_id == "n1"
        assert event.event_type == "decay"
        assert event.previous_weight == 1.0
        assert event.new_weight == 0.95

    def test_event_to_dict(self):
        """Test event serialization."""
        event = DecayEvent(
            node_id="n1",
            event_type="archive",
            previous_weight=0.5,
            new_weight=0.5,
            days_unused=180,
            reason="archival",
        )
        d = event.to_dict()
        assert d["event"] == "archive"
        assert "timestamp" in d


class TestMemoryDecayService:
    """Tests for MemoryDecayService class."""

    @pytest.fixture
    def service(self):
        """Create a MemoryDecayService instance for testing."""
        return MemoryDecayService(
            decay_rate=0.05,
            archive_threshold_days=180,
            delete_threshold_weight=0.01,
            log_dir="logs/decay_logs",
        )

    def test_service_initialization(self, service):
        """Test service is initialized correctly."""
        assert service.decay_rate == 0.05
        assert service.archive_threshold_days == 180
        assert service.delete_threshold_weight == 0.01

    def test_register_node(self, service):
        """Test registering a memory node."""
        node = MemoryNode("node_1", weight=0.9)
        service.register_node(node)
        assert "node_1" in service._nodes

    def test_touch_node(self, service):
        """Test touching a node updates last_access."""
        old_time = datetime.utcnow() - timedelta(days=60)
        node = MemoryNode("node_1", weight=0.9, last_access=old_time)
        service.register_node(node)

        service.touch_node("node_1")
        assert service._nodes["node_1"].last_access > old_time

    def test_sync_decay_cycle_no_decay_for_recent_nodes(self, service):
        """Test that recently accessed nodes don't decay."""
        node = MemoryNode("recent", weight=1.0, last_access=datetime.utcnow())
        service.register_node(node)

        result = service.run_decay_cycle_sync()
        assert result["nodes_decayed"] == 0
        assert service._nodes["recent"].weight == 1.0

    def test_sync_decay_cycle_decays_old_nodes(self, service):
        """Test that nodes unused for 30+ days do decay."""
        old_time = datetime.utcnow() - timedelta(days=60)
        node = MemoryNode("stale", weight=1.0, last_access=old_time)
        service.register_node(node)

        result = service.run_decay_cycle_sync()
        assert result["nodes_decayed"] == 1
        # 60 days = 2 decay periods, decay = 0.05 * 2 = 0.10
        assert service._nodes["stale"].weight == pytest.approx(0.90, abs=0.001)

    def test_sync_decay_cycle_archives_very_old_nodes(self, service):
        """Test that nodes unused for 180+ days are archived."""
        old_time = datetime.utcnow() - timedelta(days=200)
        node = MemoryNode("ancient", weight=1.0, last_access=old_time)
        service.register_node(node)

        result = service.run_decay_cycle_sync()
        assert result["nodes_archived"] == 1
        assert service._nodes["ancient"].archived is True

    def test_sync_decay_cycle_deletes_below_threshold(self, service):
        """Test that nodes decayed below threshold are deleted."""
        old_time = datetime.utcnow() - timedelta(days=900)
        # 900 days = 30 decay periods, decay = 0.05 * 30 = 1.5
        # new_weight = max(0, 0.5 - 1.5) = 0.0 < 0.01 → deleted
        node = MemoryNode("doomed", weight=0.5, last_access=old_time)
        service.register_node(node)

        result = service.run_decay_cycle_sync()
        assert result["nodes_deleted"] == 1
        assert "doomed" not in service._nodes

    def test_mixed_node_states(self, service):
        """Test a cycle with nodes in different states."""
        now = datetime.utcnow()

        # Recent — no decay
        service.register_node(MemoryNode("fresh", weight=1.0, last_access=now))
        # Stale — decay only
        service.register_node(
            MemoryNode("stale", weight=1.0, last_access=now - timedelta(days=60))
        )
        # Ancient — archive
        service.register_node(
            MemoryNode("ancient", weight=1.0, last_access=now - timedelta(days=200))
        )

        result = service.run_decay_cycle_sync()
        assert result["nodes_decayed"] == 2  # stale + ancient
        assert result["nodes_archived"] == 1  # ancient
        assert result["nodes_deleted"] == 0
        assert service._nodes["fresh"].weight == 1.0

    def test_already_archived_nodes_skipped(self, service):
        """Test that archived nodes aren't processed again."""
        node = MemoryNode(
            "archived",
            weight=0.5,
            last_access=datetime.utcnow() - timedelta(days=60),
            archived=True,
        )
        service.register_node(node)

        result = service.run_decay_cycle_sync()
        assert result["nodes_decayed"] == 0
        assert service._nodes["archived"].weight == 0.5  # Unchanged

    def test_get_decay_history(self, service):
        """Test retrieving decay event history."""
        old_time = datetime.utcnow() - timedelta(days=60)
        service.register_node(MemoryNode("n1", weight=1.0, last_access=old_time))

        service.run_decay_cycle_sync()
        history = service.get_decay_history()
        assert len(history) >= 1
        assert history[0]["node_id"] == "n1"

    def test_get_node_health(self, service):
        """Test aggregate health metrics."""
        service.register_node(MemoryNode("a", weight=0.9))
        service.register_node(MemoryNode("b", weight=0.5))
        service.register_node(MemoryNode("c", weight=0.1, archived=True))

        health = service.get_node_health()
        assert health["total_nodes"] == 3
        assert health["active_nodes"] == 2
        assert health["archived_nodes"] == 1
        assert health["average_weight"] == pytest.approx(0.7, abs=0.01)

    def test_decay_log_persistence(self, service):
        """Test that decay events are written to disk."""
        old_time = datetime.utcnow() - timedelta(days=60)
        service.register_node(MemoryNode("n1", weight=1.0, last_access=old_time))
        service.run_decay_cycle_sync()

        log_files = list(Path("logs/decay_logs").glob("*.jsonl"))
        assert len(log_files) >= 1

    @pytest.mark.asyncio
    async def test_async_decay_cycle_with_client_updates(self):
        """Async decay cycle processes decay, archive, and delete paths."""

        class _Client:
            async def update_node_weight(self, *_args, **_kwargs):
                return None

            async def set_node_archived(self, *_args, **_kwargs):
                return None

            async def delete_node(self, *_args, **_kwargs):
                return None

        service = MemoryDecayService(
            memory_client=_Client(),
            decay_rate=0.05,
            archive_threshold_days=180,
            delete_threshold_weight=0.01,
            log_dir="logs/decay_logs",
        )
        now = datetime.utcnow()
        service.register_node(
            MemoryNode("archive_me", 1.0, last_access=now - timedelta(days=200))
        )
        service.register_node(
            MemoryNode("delete_me", 0.02, last_access=now - timedelta(days=300))
        )

        result = await service.run_decay_cycle()
        assert result["nodes_decayed"] >= 2
        assert result["nodes_archived"] >= 1
        assert result["nodes_deleted"] >= 1

    @pytest.mark.asyncio
    async def test_restore_unknown_node_returns_none(self, service):
        """Restoring a missing node returns None."""
        event = await service.restore_node("missing")
        assert event is None

    @pytest.mark.asyncio
    async def test_restore_node_handles_client_failures(self):
        """Restore still succeeds when client writes fail."""

        class _FailingClient:
            async def set_node_archived(self, *_args, **_kwargs):
                raise RuntimeError("set failed")

            async def update_node_weight(self, *_args, **_kwargs):
                raise RuntimeError("update failed")

        service = MemoryDecayService(
            memory_client=_FailingClient(),
            log_dir="logs/decay_logs",
        )
        node = MemoryNode("n_restore", weight=0.1, archived=True)
        service.register_node(node)

        event = await service.restore_node("n_restore", boost_weight=0.6)
        assert event is not None
        assert service._nodes["n_restore"].archived is False
        assert service._nodes["n_restore"].weight == 0.6

    @pytest.mark.asyncio
    async def test_archive_and_delete_handle_client_failures(self):
        """Private archive/delete helpers handle client exceptions."""

        class _FailingClient:
            async def set_node_archived(self, *_args, **_kwargs):
                raise RuntimeError("archive failed")

            async def delete_node(self, *_args, **_kwargs):
                raise RuntimeError("delete failed")

        service = MemoryDecayService(
            memory_client=_FailingClient(),
            log_dir="logs/decay_logs",
        )
        node = MemoryNode(
            "n_delete",
            weight=0.005,
            last_access=datetime.utcnow() - timedelta(days=365),
        )
        service.register_node(node)

        archive_event = await service._archive_node(node, days_unused=365)
        delete_event = await service._delete_node(node)
        assert archive_event.event_type == "archive"
        assert delete_event.event_type == "delete"
        assert "n_delete" not in service._nodes

    def test_save_decay_log_handles_oserror(self, service, monkeypatch):
        """Decay log persistence failures should not raise."""
        event = DecayEvent(
            node_id="n1",
            event_type="decay",
            previous_weight=1.0,
            new_weight=0.9,
            days_unused=30,
            reason="test",
        )
        original_open = Path.open

        def _open_with_failure(path_obj, *args, **kwargs):
            if path_obj.suffix == ".jsonl" and path_obj.parent == service._log_dir:
                raise OSError("disk full")
            return original_open(path_obj, *args, **kwargs)

        monkeypatch.setattr(Path, "open", _open_with_failure)
        service._save_decay_log([event])
