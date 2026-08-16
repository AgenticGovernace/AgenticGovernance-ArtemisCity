"""Unit tests for the memory decay & retention service.

Naming follows docs/TEST_PLAN.md: test_<module>_<function>_<scenario>.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.integration.memory_decay import (DecayCycleResult, MemoryDecayService,
                                          MemoryNode)


def _service(tmp_path, **kwargs):
    """Build a service whose provenance log lands in a temp dir."""
    kwargs.setdefault("log_dir", str(tmp_path / "decay_logs"))
    return MemoryDecayService(**kwargs)


def _days_ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


@pytest.mark.unit
def test_memory_decay_run_cycle_fresh_nodes_unchanged(tmp_path):
    """Recently-accessed nodes are scanned but not decayed."""
    service = _service(tmp_path, decay_rate=0.1)
    for i in range(5):
        service.register_node(MemoryNode(f"mem_{i}", f"content_{i}", 0.9))

    result = service.run_decay_cycle()

    assert isinstance(result, DecayCycleResult)
    assert result.scanned == 5
    assert result.decayed == 0
    assert all(node.weight == 0.9 for node in service.all_nodes())


@pytest.mark.unit
def test_memory_decay_run_cycle_decays_stale_node(tmp_path):
    """A node unused for two decay periods loses 2 * decay_rate of weight."""
    service = _service(tmp_path, decay_rate=0.05, decay_interval_days=30)
    service.register_node(MemoryNode("stale", "x", 0.9, last_access=_days_ago(60)))

    result = service.run_decay_cycle()

    assert result.decayed == 1
    assert service.get_node("stale").weight == pytest.approx(0.8)


@pytest.mark.unit
def test_memory_decay_run_cycle_archives_old_node(tmp_path):
    """A node past the archive threshold is flagged read-only."""
    service = _service(tmp_path, decay_rate=0.0, archive_threshold_days=180)
    service.register_node(MemoryNode("ancient", "x", 0.9, last_access=_days_ago(200)))

    result = service.run_decay_cycle()

    assert result.archived == 1
    assert service.get_node("ancient").archived is True


@pytest.mark.unit
def test_memory_decay_run_cycle_deletes_low_weight_node(tmp_path):
    """A node whose weight decays below the delete threshold is removed."""
    service = _service(
        tmp_path, decay_rate=1.0, decay_interval_days=30, delete_threshold_weight=0.01
    )
    service.register_node(MemoryNode("doomed", "x", 0.05, last_access=_days_ago(60)))

    result = service.run_decay_cycle()

    assert result.deleted == 1
    assert service.get_node("doomed") is None


@pytest.mark.unit
def test_memory_decay_run_cycle_archived_node_skipped(tmp_path):
    """Once archived, a node is excluded from subsequent decay passes."""
    service = _service(tmp_path, decay_rate=0.05, archive_threshold_days=180)
    service.register_node(MemoryNode("a", "x", 0.9, last_access=_days_ago(200)))

    service.run_decay_cycle()  # archives the node
    second = service.run_decay_cycle()  # archived -> skipped

    assert second.decayed == 0
    assert service.get_node("a").archived is True


@pytest.mark.unit
def test_memory_decay_run_cycle_writes_provenance(tmp_path):
    """Decay events are appended to a dated JSONL provenance log."""
    log_dir = tmp_path / "decay_logs"
    service = MemoryDecayService(
        decay_rate=0.05, decay_interval_days=30, log_dir=str(log_dir)
    )
    service.register_node(MemoryNode("n", "x", 0.9, last_access=_days_ago(60)))

    service.run_decay_cycle()

    files = list(log_dir.glob("*.jsonl"))
    assert files, "expected a provenance JSONL file to be written"
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    event = json.loads(lines[0])
    assert event["event"] == "memory_decay"
    assert event["node_id"] == "n"
    assert event["previous_weight"] == 0.9
    assert event["new_weight"] == pytest.approx(0.8)


@pytest.mark.unit
def test_memory_decay_run_cycle_invokes_sink(tmp_path):
    """The optional sink is called once per applied weight change."""
    calls = []
    service = _service(
        tmp_path,
        decay_rate=0.05,
        decay_interval_days=30,
        sink=lambda node, prev, new: calls.append((node.node_id, prev, new)),
    )
    service.register_node(MemoryNode("s", "x", 0.9, last_access=_days_ago(30)))

    service.run_decay_cycle()

    assert len(calls) == 1
    assert calls[0][0] == "s"


@pytest.mark.unit
def test_memory_decay_restore_node_boosts_and_unarchives(tmp_path):
    """Restoring a node clears the archive flag and applies the boost."""
    service = _service(tmp_path, restore_boost=0.10, enable_provenance=False)
    node = service.register_node(MemoryNode("r", "x", 0.5))
    node.archived = True

    restored = service.restore_node("r")

    assert restored is not None
    assert restored.archived is False
    assert restored.weight == pytest.approx(0.55)
