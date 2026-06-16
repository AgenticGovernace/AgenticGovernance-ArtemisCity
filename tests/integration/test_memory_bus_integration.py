"""Tests for the memory bus (src/integration/memory_bus.py)."""

import sys

sys.modules.pop("integration.memory_bus", None)

import pytest
from pathlib import Path
from integration.memory_bus import MemoryBus


# ---------------------------------------------------------------------------
# Lightweight stubs for ObsidianManager and LocalVectorStore
# ---------------------------------------------------------------------------
class _StubObsidianManager:
    """Minimal stand-in for ObsidianManager."""

    def __init__(self, vault_path=None):
        self.vault_path = Path(vault_path) if vault_path else None
        self.written = {}
        self.notes = {}

    def write_note(self, relative_path, content):
        self.written[relative_path] = content

    def read_note(self, relative_path):
        return self.notes.get(relative_path)


class _FailingObsidianManager(_StubObsidianManager):
    def write_note(self, relative_path, content):
        raise OSError("Obsidian write failed")


class _StubVectorStore:
    """Minimal stand-in for LocalVectorStore."""

    def __init__(self):
        self.docs = {}
        self.deleted = []

    def upsert(self, doc_id, content, metadata=None):
        self.docs[doc_id] = (content, metadata)

    def delete(self, doc_id):
        self.deleted.append(doc_id)
        self.docs.pop(doc_id, None)

    def count(self):
        return len(self.docs)

    def query(self, query_text, top_k=3, include_content=False):
        results = []
        for doc_id, (content, metadata) in list(self.docs.items())[:top_k]:
            results.append((doc_id, 0.9, metadata, content if include_content else None))
        return results


class _StubGovernanceMonitor:
    def __init__(self):
        self.failures = []
        self.successes = 0

    def record_failure(self, event):
        self.failures.append(event)
        return len(self.failures) >= 3

    def record_success(self):
        self.successes += 1


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestMemoryBusWrite:
    @pytest.fixture
    def bus(self):
        obs = _StubObsidianManager()
        vec = _StubVectorStore()
        return MemoryBus(obsidian_manager=obs, vector_store=vec)

    def test_write_to_both_stores(self, bus):
        result = bus.write_note_with_embedding("notes/test.md", "hello world")
        assert result["status"] == "success"
        assert result["doc_id"] == "notes/test.md"
        assert result["path"] == "notes/test.md"
        assert bus.obsidian_manager.written["notes/test.md"] == "hello world"
        assert "notes/test.md" in bus.vector_store.docs

    def test_write_latencies_populated(self, bus):
        result = bus.write_note_with_embedding("notes/test.md", "content")
        assert result["vector_latency_ms"] is not None
        assert result["file_latency_ms"] is not None
        assert result["total_latency_ms"] is not None
        assert result["total_latency_ms"] >= 0

    def test_write_with_metadata(self, bus):
        result = bus.write_note_with_embedding(
            "notes/test.md", "content", metadata={"tag": "important"}
        )
        assert result["status"] == "success"
        _, meta = bus.vector_store.docs["notes/test.md"]
        assert meta["tag"] == "important"
        assert meta["path"] == "notes/test.md"

    def test_write_no_embed(self, bus):
        result = bus.write_note_with_embedding("notes/test.md", "content", embed=False)
        assert result["status"] == "success"
        assert result["vector_latency_ms"] is None
        assert "notes/test.md" not in bus.vector_store.docs
        assert bus.obsidian_manager.written["notes/test.md"] == "content"


class TestMemoryBusWriteFailure:
    def test_obsidian_failure_rolls_back_vector(self):
        obs = _FailingObsidianManager()
        vec = _StubVectorStore()
        bus = MemoryBus(obsidian_manager=obs, vector_store=vec)
        with pytest.raises(OSError):
            bus.write_note_with_embedding("notes/test.md", "content")
        # Vector store should have rolled back
        assert "notes/test.md" not in vec.docs
        assert "notes/test.md" in vec.deleted

    def test_obsidian_failure_records_governance(self):
        obs = _FailingObsidianManager()
        vec = _StubVectorStore()
        gov = _StubGovernanceMonitor()
        bus = MemoryBus(obsidian_manager=obs, vector_store=vec, governance_monitor=gov)
        with pytest.raises(OSError):
            bus.write_note_with_embedding("notes/test.md", "content")
        assert len(gov.failures) == 1
        assert gov.failures[0]["path"] == "notes/test.md"

    def test_no_embed_no_rollback_on_failure(self):
        obs = _FailingObsidianManager()
        vec = _StubVectorStore()
        bus = MemoryBus(obsidian_manager=obs, vector_store=vec)
        with pytest.raises(OSError):
            bus.write_note_with_embedding("notes/test.md", "content", embed=False)
        assert vec.deleted == []


class TestMemoryBusRead:
    @pytest.fixture
    def bus(self):
        obs = _StubObsidianManager()
        obs.notes["notes/exact.md"] = "exact content"
        vec = _StubVectorStore()
        vec.upsert("vec_doc", "vector content", {"path": "notes/vec.md"})
        return MemoryBus(obsidian_manager=obs, vector_store=vec)

    def test_read_exact_path(self, bus):
        results = bus.read("query", relative_path="notes/exact.md")
        assert len(results) >= 1
        assert results[0]["source"] == "exact"
        assert results[0]["content"] == "exact content"
        assert results[0]["score"] == 1.0

    def test_read_exact_path_not_found(self, bus):
        results = bus.read("query", relative_path="notes/missing.md")
        # Falls through to vector search
        assert all(r["source"] != "exact" for r in results)

    def test_read_vector_fallback(self, bus):
        results = bus.read("query")
        assert any(r["source"] == "vector" for r in results)

    def test_read_empty_vector_store(self):
        obs = _StubObsidianManager()
        vec = _StubVectorStore()  # empty
        bus = MemoryBus(obsidian_manager=obs, vector_store=vec)
        results = bus.read("query")
        assert results == []

    def test_read_max_results(self, bus):
        results = bus.read("query", max_results=1)
        assert len(results) <= 1


class TestMemoryBusKeywordScan:
    def test_keyword_scan(self, tmp_path):
        vault = tmp_path / "vault"
        folder = vault / "notes"
        folder.mkdir(parents=True)
        (folder / "a.md").write_text("This mentions memory bus operations")
        (folder / "b.md").write_text("Unrelated content about cats")

        obs = _StubObsidianManager(vault_path=str(vault))
        vec = _StubVectorStore()
        bus = MemoryBus(
            obsidian_manager=obs, vector_store=vec, search_dirs=["notes"]
        )
        results = bus.read("memory bus")
        keyword_hits = [r for r in results if r["source"] == "keyword"]
        assert len(keyword_hits) == 1
        assert "notes/a.md" in keyword_hits[0]["path"]

    def test_keyword_scan_no_vault_path(self):
        obs = _StubObsidianManager(vault_path=None)
        vec = _StubVectorStore()
        bus = MemoryBus(obsidian_manager=obs, vector_store=vec, search_dirs=["notes"])
        hits = bus._keyword_scan("query", 5)
        assert hits == []

    def test_keyword_scan_missing_folder(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        obs = _StubObsidianManager(vault_path=str(vault))
        vec = _StubVectorStore()
        bus = MemoryBus(obsidian_manager=obs, vector_store=vec, search_dirs=["nonexistent"])
        hits = bus._keyword_scan("query", 5)
        assert hits == []


class TestMemoryBusGovernance:
    def test_success_records_governance(self):
        obs = _StubObsidianManager()
        vec = _StubVectorStore()
        gov = _StubGovernanceMonitor()
        bus = MemoryBus(obsidian_manager=obs, vector_store=vec, governance_monitor=gov)
        bus.write_note_with_embedding("notes/test.md", "content")
        assert gov.successes == 1

    def test_no_governance_monitor_ok(self):
        obs = _StubObsidianManager()
        vec = _StubVectorStore()
        bus = MemoryBus(obsidian_manager=obs, vector_store=vec, governance_monitor=None)
        # Should not raise
        bus.write_note_with_embedding("notes/test.md", "content")


class TestNormalizeDocId:
    def test_spaces_replaced(self):
        assert MemoryBus._normalize_doc_id("my note.md") == "my_note.md"

    def test_no_spaces(self):
        assert MemoryBus._normalize_doc_id("note.md") == "note.md"
