"""Focused coverage for the lightweight kernel memory backends."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.kernel.memory_bus as kernel_memory
from app.kernel.memory_bus import (FileMemoryBackend, MemoryBackend, MemoryBus,
                                   VectorMemoryBackend)


class _RecordingBackend(MemoryBackend):
    """Small custom backend used to verify ``MemoryBus`` delegation."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, dict | None]] = []
        self.reads: list[tuple[str, int]] = []

    def write(self, content, metadata=None):
        self.writes.append((content, metadata))
        return "custom-id"

    def read(self, query, limit: int = 10):
        self.reads.append((query, limit))
        return [{"content": "custom result"}]


class _ParentCallingBackend(MemoryBackend):
    """Expose the defensive abstract-method implementations for testing."""

    def write(self, content, metadata=None):
        return super().write(content, metadata)

    def read(self, query, limit: int = 10):
        return super().read(query, limit)


def test_memory_backend_abstract_methods_fail_closed() -> None:
    backend = _ParentCallingBackend()

    with pytest.raises(NotImplementedError):
        backend.write("content")
    with pytest.raises(NotImplementedError):
        backend.read("query")


def test_file_backend_writes_and_reads_case_insensitively_with_limit(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "memory"
    backend = FileMemoryBackend(str(store_path))

    written_path = backend.write(
        "MiXeD legal memory",
        {"source": "unit-test", "sequence": 1},
    )

    assert written_path is not None
    payload = json.loads(Path(written_path).read_text(encoding="utf-8"))
    assert payload["content"] == "MiXeD legal memory"
    assert payload["metadata"] == {"source": "unit-test", "sequence": 1}
    assert isinstance(payload["timestamp"], float)

    # A lexically newer valid record, malformed JSON, and a non-JSON file
    # exercise ordering, limit enforcement, corrupt-record tolerance, and the
    # extension filter in one realistic directory scan.
    (store_path / "zz_valid.json").write_text(
        json.dumps(
            {
                "content": "A second MIXED memory",
                "metadata": {"sequence": 2},
                "timestamp": 2.0,
            }
        ),
        encoding="utf-8",
    )
    (store_path / "zzz_invalid.json").write_text("{not-json", encoding="utf-8")
    (store_path / "zzzz_ignore.txt").write_text("mixed", encoding="utf-8")

    results = backend.read("mixed", limit=1)

    assert results == [
        {
            "content": "A second MIXED memory",
            "metadata": {"sequence": 2},
            "timestamp": 2.0,
        }
    ]
    assert backend.read("absent") == []

    # Reusing an existing directory must not attempt to recreate it.
    assert FileMemoryBackend(str(store_path)).base_path == str(store_path)


def test_file_backend_handles_nonpositive_limit_and_missing_store(
    tmp_path: Path,
) -> None:
    backend = FileMemoryBackend(str(tmp_path / "memory"))

    assert backend.read("anything", limit=0) == []

    backend.base_path = str(tmp_path / "does-not-exist")
    assert backend.read("anything") == []


def test_file_backend_returns_none_when_write_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = FileMemoryBackend(str(tmp_path / "memory"))

    with patch.object(
        kernel_memory,
        "open",
        side_effect=OSError("read-only store"),
        create=True,
    ):
        assert backend.write("content") is None

    assert "[Memory] Write failed: read-only store" in capsys.readouterr().out


def test_vector_backend_uses_real_local_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vector_db = tmp_path / "kernel-vectors.db"
    monkeypatch.setenv("ARTEMIS_VECTOR_DB", str(vector_db))

    # Keep this backend test isolated from the process-wide audit logger; the
    # vector store itself remains the real SQLite implementation.
    import src.mcp.vector_store as vector_store_module

    monkeypatch.setattr(vector_store_module, "_get_run_logger", lambda: None)
    backend = VectorMemoryBackend()
    metadata = {
        "doc_id": "legal-memory-1",
        "source": "test",
        "stored_at": 123.0,
    }

    doc_id = backend.write("legal precedent and contract law", metadata)
    results = backend.read("contract law", limit=1)

    assert vector_db.exists()
    assert doc_id == "legal-memory-1"
    assert metadata["doc_id"] == "legal-memory-1"  # caller input is not mutated
    assert len(results) == 1
    assert results[0]["content"] == "legal precedent and contract law"
    assert results[0]["metadata"]["source"] == "test"
    assert results[0]["timestamp"] == 123.0
    assert isinstance(results[0]["similarity"], float)

    generated_id = backend.write("a second memory")
    assert generated_id is not None
    assert len(generated_id) == 32


def test_vector_backend_maps_last_access_timestamp() -> None:
    store = MagicMock()
    store.query.return_value = [
        ("doc-1", 0.75, {"last_access": "2026-07-14T12:00:00Z"}, "memory")
    ]
    backend = VectorMemoryBackend.__new__(VectorMemoryBackend)
    backend._available = True
    backend.vector_store = store

    assert backend.read("memory", limit=3) == [
        {
            "content": "memory",
            "metadata": {"last_access": "2026-07-14T12:00:00Z"},
            "timestamp": "2026-07-14T12:00:00Z",
            "similarity": 0.75,
        }
    ]
    store.query.assert_called_once_with("memory", top_k=3, include_content=True)


def test_vector_backend_handles_unavailable_store(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch(
        "src.mcp.vector_store.LocalVectorStore",
        side_effect=RuntimeError("driver unavailable"),
    ):
        backend = VectorMemoryBackend()

    assert backend._available is False
    assert backend.vector_store is None
    assert backend.write("content") is None
    assert backend.read("query") == []
    output = capsys.readouterr().out
    assert "[Memory] VectorStore not available: driver unavailable" in output
    assert "[Memory] Vector backend not available" in output

    # The explicit ``vector_store is None`` guard is also fail-closed even if
    # availability was accidentally left true by an external adapter.
    backend._available = True
    assert backend.write("content") is None
    assert backend.read("query") == []


def test_vector_backend_contains_adapter_failures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = MagicMock()
    store.upsert.side_effect = RuntimeError("upsert failed")
    store.query.side_effect = RuntimeError("query failed")
    backend = VectorMemoryBackend.__new__(VectorMemoryBackend)
    backend._available = True
    backend.vector_store = store

    assert backend.write("content", {"doc_id": "fixed"}) is None
    assert backend.read("query", limit=4) == []
    output = capsys.readouterr().out
    assert "[Memory] Vector write failed: upsert failed" in output
    assert "[Memory] Vector search failed: query failed" in output


def test_memory_bus_delegates_to_custom_backend_and_tracks_semantic_state() -> None:
    backend = _RecordingBackend()
    bus = MemoryBus(backend_type="vector", backend=backend)

    assert bus.write("remember", {"source": "caller"}) == "custom-id"
    assert bus.read("recall", limit=2) == [{"content": "custom result"}]
    assert backend.writes == [("remember", {"source": "caller"})]
    assert backend.reads == [("recall", 2)]
    assert bus.is_semantic() is True

    backend._available = False
    assert bus.is_semantic() is False


def test_memory_bus_selects_file_vector_and_unknown_backends(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file_path = tmp_path / "file"
    file_bus = MemoryBus("file", file_base_path=str(file_path))
    assert isinstance(file_bus.backend, FileMemoryBackend)
    assert file_bus.is_semantic() is False
    assert file_bus.write("persisted", {"source": "bus"}) is not None
    assert file_bus.read("PERSISTED", limit=1)[0]["content"] == "persisted"

    vector_backend = MagicMock(spec=VectorMemoryBackend)
    vector_backend._available = True
    with patch.object(
        kernel_memory, "VectorMemoryBackend", return_value=vector_backend
    ) as vector_factory:
        vector_bus = MemoryBus("vector")
    vector_factory.assert_called_once_with()
    assert vector_bus.backend is vector_backend
    assert vector_bus.is_semantic() is True

    fallback_path = tmp_path / "fallback"
    fallback_bus = MemoryBus("not-a-backend", file_base_path=str(fallback_path))
    assert isinstance(fallback_bus.backend, FileMemoryBackend)
    assert fallback_bus.backend_type == "file"
    assert fallback_bus.is_semantic() is False
    assert "Unknown backend not-a-backend" in capsys.readouterr().out
