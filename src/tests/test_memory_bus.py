from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.integration.governance import GovernanceMonitor
from src.integration.memory_bus import MemoryBus
from src.integration.memory_decay import MemoryDecayService
from src.mcp.vector_store import LocalVectorStore
from src.obsidian_integration.manager import ObsidianManager


def test_write_note_with_embedding_syncs_semantic_and_file(tmp_path):
    """Test that write note with embedding syncs semantic and file.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)

    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    bus = MemoryBus(manager, vector_store)

    result = bus.write_note_with_embedding(
        "Agent Outputs/sample.md",
        "hello world",
        metadata={"agent": "tester"},
    )

    assert result["status"] == "success"
    assert vector_store.count() == 1
    assert (vault / "Agent Outputs" / "sample.md").is_file()


def test_read_falls_back_to_vector_search(tmp_path):
    """Test that read falls back to vector search.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)

    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    vector_store.upsert("doc1", "mars mission overview", {"path": "notes/doc1.md"})

    bus = MemoryBus(manager, vector_store)
    results = bus.read("mars mission", max_results=1)

    assert len(results) == 1
    assert results[0]["source"] == "vector"
    assert results[0]["path"] == "notes/doc1.md"


def test_vector_write_rolls_back_on_file_failure(tmp_path):
    """Test that vector write rolls back on file failure.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """

    class FailingManager:
        def __init__(self, vault_root):
            self.vault_path = vault_root

        def write_note(self, *args, **kwargs):
            raise IOError("disk full")

        def read_note(self, *args, **kwargs):
            return None

    vector_store = MagicMock()
    vector_store.upsert = MagicMock()
    vector_store.delete = MagicMock()

    bus = MemoryBus(FailingManager(tmp_path), vector_store)

    with pytest.raises(IOError):
        bus.write_note_with_embedding("note.md", "content")

    vector_store.delete.assert_called_once()


def test_governance_alert_on_repeated_failures(tmp_path):
    """Test that governance alert on repeated failures.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """

    class FailingManager:
        def __init__(self, vault_root):
            self.vault_path = vault_root

        def write_note(self, *args, **kwargs):
            raise IOError("disk full")

        def read_note(self, *args, **kwargs):
            return None

    vector_store = MagicMock()
    vector_store.upsert = MagicMock()
    vector_store.delete = MagicMock()

    governance = GovernanceMonitor(
        alert_threshold=1, log_path=str(tmp_path / "gov.log")
    )
    bus = MemoryBus(
        FailingManager(tmp_path), vector_store, governance_monitor=governance
    )

    with pytest.raises(IOError):
        bus.write_note_with_embedding("note.md", "content")

    assert governance.get_failure_streak() == 1


def test_memory_decay_cycle_updates_durable_vector_state(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    vector_store.upsert("notes/stale.md", "stale memory")
    vector_store.update_decay_state(
        "notes/stale.md",
        weight=0.9,
        last_access=(datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
        archived=False,
    )
    decay = MemoryDecayService(
        decay_rate=0.05,
        decay_interval_days=30,
        enable_provenance=False,
    )
    bus = MemoryBus(manager, vector_store, memory_decay_service=decay)

    result = bus.run_memory_decay_cycle()

    assert result.decayed == 1
    persisted = vector_store.get_decay_records()[0]
    assert persisted["weight"] == pytest.approx(0.8)


def test_read_restores_archived_memory_and_refreshes_access(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    vector_store.upsert(
        "notes/archived.md", "recover this memory", {"path": "notes/archived.md"}
    )
    old_access = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    vector_store.update_decay_state(
        "notes/archived.md",
        weight=0.5,
        last_access=old_access,
        archived=True,
    )
    decay = MemoryDecayService(enable_provenance=False)
    bus = MemoryBus(manager, vector_store, memory_decay_service=decay)

    results = bus.read("recover", max_results=1)

    assert results
    persisted = vector_store.get_decay_records()[0]
    assert persisted["archived"] is False
    assert persisted["weight"] == pytest.approx(0.55)
    assert persisted["last_access"] != old_access
