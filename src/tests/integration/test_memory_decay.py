"""Integration tests for memory decay functionality.

Tests the ``MemoryDecayService`` and ``MemoryNode`` classes from
``src.integration.memory_decay``.
"""

import builtins
import logging
import sys
from datetime import UTC
from pathlib import Path

_repo = str(Path(__file__).resolve().parents[3])
if _repo not in sys.path:
    sys.path.insert(0, _repo)
for _key in [
    k for k in sys.modules if k == "integration" or k.startswith("integration.")
]:
    del sys.modules[_key]

from datetime import datetime, timedelta, timezone

import pytest

from src.integration.memory_decay import (DecayCycleResult, MemoryDecayService,
                                          MemoryNode)


class TestMemoryNode:
    """Tests for MemoryNode class."""

    def test_node_initialization(self):
        """Test memory node is initialized correctly."""
        node = MemoryNode(node_id="mem_1", content="hello", weight=0.8)
        assert node.node_id == "mem_1"
        assert node.weight == 0.8
        assert node.archived is False

    def test_node_defaults(self):
        """Test memory node default values."""
        node = MemoryNode(node_id="mem_2", content="data", weight=1.0)
        assert node.weight == 1.0
        assert node.archived is False
        assert isinstance(node.last_access, datetime)
        assert isinstance(node.created_at, datetime)

    def test_node_content(self):
        """Test node stores content."""
        node = MemoryNode(node_id="mem_3", content="payload", weight=0.5)
        assert node.content == "payload"


class TestDecayCycleResult:
    """Tests for DecayCycleResult dataclass."""

    def test_defaults(self):
        """Test default values."""
        result = DecayCycleResult()
        assert result.scanned == 0
        assert result.decayed == 0
        assert result.archived == 0
        assert result.deleted == 0
        assert result.events == []

    def test_event_accumulation(self):
        """Test that events can be appended."""
        result = DecayCycleResult()
        result.events.append({"event": "test"})
        assert len(result.events) == 1


class TestMemoryDecayService:
    """Tests for MemoryDecayService class."""

    @pytest.fixture
    def service(self, tmp_path):
        """Create a MemoryDecayService instance for testing."""
        return MemoryDecayService(
            decay_rate=0.05,
            archive_threshold_days=180,
            delete_threshold_weight=0.01,
            log_dir=str(tmp_path / "decay_logs"),
        )

    def test_service_initialization(self, service):
        """Test service is initialized correctly."""
        assert service.decay_rate == 0.05
        assert service.archive_threshold_days == 180
        assert service.delete_threshold_weight == 0.01

    def test_invalid_decay_interval(self):
        """decay_interval_days <= 0 raises ValueError."""
        with pytest.raises(ValueError):
            MemoryDecayService(decay_interval_days=0)

    def test_register_node(self, service):
        """Test registering a memory node."""
        node = MemoryNode("node_1", content="c", weight=0.9)
        service.register_node(node)
        assert "node_1" in service.nodes

    def test_register_nodes_bulk(self, service):
        """Test bulk registration."""
        nodes = [MemoryNode(f"n{i}", content="c", weight=0.5) for i in range(5)]
        count = service.register_nodes(nodes)
        assert count == 5
        assert len(service.nodes) == 5

    def test_get_node(self, service):
        """Test getting a node by id."""
        node = MemoryNode("x", content="c", weight=0.5)
        service.register_node(node)
        assert service.get_node("x") is node
        assert service.get_node("missing") is None

    def test_all_nodes(self, service):
        """Test listing all nodes."""
        service.register_node(MemoryNode("a", content="c", weight=1.0))
        service.register_node(MemoryNode("b", content="c", weight=0.5))
        assert len(service.all_nodes()) == 2

    def test_record_access(self, service):
        """Test that record_access updates last_access."""
        old_time = datetime.now(timezone.utc) - timedelta(days=60)
        node = MemoryNode("node_1", content="c", weight=0.9, last_access=old_time)
        service.register_node(node)

        result = service.record_access("node_1")
        assert result is not None
        assert service.nodes["node_1"].last_access > old_time

    def test_record_access_missing_node(self, service):
        """record_access returns None for unknown node."""
        assert service.record_access("nonexistent") is None

    def test_decay_cycle_no_decay_for_recent_nodes(self, service):
        """Test that recently accessed nodes don't decay."""
        now = datetime.now(timezone.utc)
        node = MemoryNode("recent", content="c", weight=1.0, last_access=now)
        service.register_node(node)

        result = service.run_decay_cycle(now=now)
        assert isinstance(result, DecayCycleResult)
        assert result.decayed == 0
        assert service.nodes["recent"].weight == 1.0

    def test_decay_cycle_decays_old_nodes(self, service):
        """Test that nodes unused for 30+ days do decay."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=60)
        node = MemoryNode("stale", content="c", weight=1.0, last_access=old_time)
        service.register_node(node)

        result = service.run_decay_cycle(now=now)
        assert result.decayed == 1
        # 60 days = 2 decay periods, decay = 0.05 * 2 = 0.10
        assert service.nodes["stale"].weight == pytest.approx(0.90, abs=0.001)

    def test_decay_cycle_archives_very_old_nodes(self, service):
        """Test that nodes unused for 180+ days are archived."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=200)
        node = MemoryNode("ancient", content="c", weight=1.0, last_access=old_time)
        service.register_node(node)

        result = service.run_decay_cycle(now=now)
        assert result.archived == 1
        assert service.nodes["ancient"].archived is True

    def test_decay_cycle_deletes_below_threshold(self, service):
        """Test that nodes decayed below threshold are deleted."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=900)
        node = MemoryNode("doomed", content="c", weight=0.5, last_access=old_time)
        service.register_node(node)

        result = service.run_decay_cycle(now=now)
        assert result.deleted == 1
        assert "doomed" not in service.nodes

    def test_mixed_node_states(self, service):
        """Test a cycle with nodes in different states."""
        now = datetime.now(timezone.utc)

        service.register_node(
            MemoryNode("fresh", content="c", weight=1.0, last_access=now)
        )
        service.register_node(
            MemoryNode(
                "stale", content="c", weight=1.0, last_access=now - timedelta(days=60)
            )
        )
        service.register_node(
            MemoryNode(
                "ancient",
                content="c",
                weight=1.0,
                last_access=now - timedelta(days=200),
            )
        )

        result = service.run_decay_cycle(now=now)
        assert result.decayed == 2  # stale + ancient
        assert result.archived == 1  # ancient
        assert result.deleted == 0
        assert service.nodes["fresh"].weight == 1.0

    def test_already_archived_nodes_skipped(self, service):
        """Test that archived nodes aren't processed again."""
        now = datetime.now(timezone.utc)
        node = MemoryNode(
            "archived",
            content="c",
            weight=0.5,
            last_access=now - timedelta(days=60),
            archived=True,
        )
        service.register_node(node)

        result = service.run_decay_cycle(now=now)
        assert result.decayed == 0
        assert service.nodes["archived"].weight == 0.5

    def test_restore_node(self, service):
        """Test restoring an archived node."""
        node = MemoryNode("n1", content="c", weight=0.5, archived=True)
        service.register_node(node)

        restored = service.restore_node("n1")
        assert restored is not None
        assert restored.archived is False
        # restore_boost default is 0.10 → 0.5 * 1.10 = 0.55
        assert restored.weight == pytest.approx(0.55, abs=0.01)

    def test_restore_node_ignores_sink_failures(self, tmp_path):
        def _sink(_node, _previous, _new_weight):
            raise RuntimeError("sink failed")
        service = MemoryDecayService(log_dir=str(tmp_path / "restore_sink"), sink=_sink)
        node = MemoryNode("n1", content="c", weight=0.5, archived=True)
        service.register_node(node)
        restored = service.restore_node("n1")
        assert restored is not None
        assert restored.archived is False
        assert restored.weight == pytest.approx(0.55, abs=0.01)

    def test_restore_unknown_node_returns_none(self, service):
        """Restoring a missing node returns None."""
        result = service.restore_node("missing")
        assert result is None

    def test_decay_cycle_generates_provenance_events(self, service):
        """Decay events are included in the result."""
        now = datetime.now(timezone.utc)
        service.register_node(
            MemoryNode(
                "n1", content="c", weight=1.0, last_access=now - timedelta(days=60)
            )
        )
        result = service.run_decay_cycle(now=now)
        assert len(result.events) >= 1
        assert result.events[0]["node_id"] == "n1"

    def test_decay_log_persistence(self, service):
        """Test that decay events are written to disk."""
        now = datetime.now(timezone.utc)
        service.register_node(
            MemoryNode(
                "n1", content="c", weight=1.0, last_access=now - timedelta(days=60)
            )
        )
        service.run_decay_cycle(now=now)
        log_files = list(service.log_dir.glob("*.jsonl"))
        assert len(log_files) >= 1

    def test_provenance_write_oserror_is_non_fatal(
        self,
        service,
        monkeypatch,
        caplog,
    ):
        now = datetime.now(UTC)
        service.register_node(
            MemoryNode(
                "n1", content="c", weight=1.0, last_access=now - timedelta(days=60)
            )
        )
        original_open = builtins.open
        target_log = service.log_dir / f"{now.date().isoformat()}.jsonl"
        opened = {"count": 0}

        def _open_with_failure(path_obj, *args, **kwargs):
            if Path(path_obj) == target_log:
                opened["count"] += 1
                raise OSError("disk full")
            return original_open(path_obj, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", _open_with_failure)
        caplog.set_level(logging.WARNING)
        result = service.run_decay_cycle(now=now)
        assert result.decayed == 1
        assert result.deleted == 0
        assert result.archived == 0
        assert service.nodes["n1"].weight == pytest.approx(0.90, abs=0.001)
        assert opened["count"] == 1
        assert "Could not write memory decay provenance log" in caplog.text

    def test_provenance_disabled(self, tmp_path):
        """No provenance files when enable_provenance=False."""
        svc = MemoryDecayService(
            log_dir=str(tmp_path / "no_prov"),
            enable_provenance=False,
        )
        now = datetime.now(timezone.utc)
        svc.register_node(
            MemoryNode(
                "n1", content="c", weight=1.0, last_access=now - timedelta(days=60)
            )
        )
        svc.run_decay_cycle(now=now)
        log_dir = tmp_path / "no_prov"
        log_files = list(log_dir.glob("*.jsonl")) if log_dir.exists() else []
        assert len(log_files) == 0

    def test_sink_callback(self, tmp_path):
        """Weight-change sink is called on decay."""
        calls = []

        def _sink(node, prev, new):
            calls.append((node.node_id, prev, new))

        svc = MemoryDecayService(
            log_dir=str(tmp_path / "sink_test"),
            sink=_sink,
        )
        now = datetime.now(timezone.utc)
        svc.register_node(
            MemoryNode(
                "n1", content="c", weight=1.0, last_access=now - timedelta(days=60)
            )
        )
        svc.run_decay_cycle(now=now)
        assert len(calls) == 1
        assert calls[0][0] == "n1"
