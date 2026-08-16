"""Behavioral tests for transport-neutral memory projection adapters."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.memory.backends.obsidian import ObsidianMemoryProjection
from src.memory.backends.vector import VectorMemoryProjection
from src.memory.models import MemoryRecord, MemoryWriteCommand


class RecordingObsidianManager:
    """Capture the externally visible note written by a projection."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def write_note(self, relative_path: str, content: str) -> None:
        self.writes.append((relative_path, content))


class RecordingVectorStore:
    """Capture semantic documents materialized by a projection."""

    def __init__(self) -> None:
        self.upserts: list[tuple[str, str, dict[str, object]]] = []

    def upsert(self, doc_id: str, content: str, metadata: dict[str, object]) -> None:
        self.upserts.append((doc_id, content, metadata))


def memory_record(**overrides: object) -> MemoryRecord:
    """Build one immutable memory version with independently chosen values."""
    values: dict[str, object] = {
        "record_id": "record-42",
        "memory_id": "memory-17",
        "namespace": "reviewed",
        "key": "daily/brief",
        "projection_path": "Memory/reviewed/daily/brief.md",
        "version": 3,
        "content": "# Daily brief\n\nExact body.\n",
        "content_sha256": "sha256-daily-brief",
        "metadata": {"topic": "routing"},
        "idempotency_key": "request-42",
        "principal_id": "principal-7",
        "parent_provenance_id": "parent-provenance-7",
        "completion_provenance_id": "completion-provenance-42",
        "created_at": datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return MemoryRecord(**values)  # type: ignore[arg-type]


def test_mcp_command_default_path_is_projected_under_reviewed_namespace() -> None:
    command = MemoryWriteCommand(
        namespace="reviewed",
        key="daily/brief",
        content="body",
        metadata={},
        idempotency_key="mcp-request-1",
        principal_id="mcp-principal",
        parent_provenance_id="mcp-provenance",
        requested_projections=("obsidian",),
    )

    assert command.projection_path == "Memory/reviewed/daily/brief.md"


def test_obsidian_projection_preserves_path_and_renders_durable_frontmatter() -> None:
    manager = RecordingObsidianManager()
    projection = ObsidianMemoryProjection(manager)
    record = memory_record(projection_path="Agent Outputs/sample.md")

    projection.project(record)

    expected_note = (
        "---\n"
        'record_id: "record-42"\n'
        'memory_id: "memory-17"\n'
        'namespace: "reviewed"\n'
        'key: "daily/brief"\n'
        "version: 3\n"
        'content_sha256: "sha256-daily-brief"\n'
        'provenance_id: "completion-provenance-42"\n'
        "---\n\n"
        "# Daily brief\n\nExact body.\n"
    )
    assert manager.writes == [("Agent Outputs/sample.md", expected_note)]


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/outside.md",
        "../outside.md",
        "Memory/../outside.md",
        "Memory/./brief.md",
        "Memory//brief.md",
        "C:/outside.md",
        "C:\\outside.md",
    ],
)
def test_obsidian_projection_rejects_unsafe_record_path_before_write(
    unsafe_path: str,
) -> None:
    manager = RecordingObsidianManager()
    projection = ObsidianMemoryProjection(manager)
    record = memory_record()
    object.__setattr__(record, "projection_path", unsafe_path)

    with pytest.raises(ValueError, match="projection path"):
        projection.project(record)

    assert manager.writes == []


def test_vector_projection_uses_logical_memory_id_and_canonical_metadata() -> None:
    vector_store = RecordingVectorStore()
    projection = VectorMemoryProjection(vector_store)
    record = memory_record(
        projection_path="Agent Outputs/sample.md",
        metadata={"topic": "routing", "path": "untrusted-override.md"},
    )

    projection.project(record)

    assert vector_store.upserts == [
        (
            "memory-17",
            "# Daily brief\n\nExact body.\n",
            {
                "topic": "routing",
                "path": "Agent Outputs/sample.md",
                "projection_path": "Agent Outputs/sample.md",
                "namespace": "reviewed",
                "key": "daily/brief",
                "version": 3,
                "content_sha256": "sha256-daily-brief",
                "provenance_id": "completion-provenance-42",
            },
        )
    ]
