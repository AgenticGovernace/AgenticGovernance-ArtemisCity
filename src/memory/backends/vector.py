"""Semantic vector materialization for canonical memory versions."""

from __future__ import annotations

from typing import Protocol

from src.memory.models import MemoryRecord


class VectorStore(Protocol):
    """Minimal vector-store boundary required by the projection."""

    def upsert(self, doc_id: str, content: str, metadata: dict[str, object]) -> object:
        """Create or replace one semantic document."""
        ...


class VectorMemoryProjection:
    """Project immutable memory records under their durable logical ID."""

    name = "vector"

    def __init__(self, vector_store: VectorStore) -> None:
        self._vector_store = vector_store

    def project(self, record: MemoryRecord) -> None:
        """Upsert content and canonical search metadata without rollback deletes."""
        metadata = dict(record.metadata)
        metadata.update(
            {
                "path": record.projection_path,
                "projection_path": record.projection_path,
                "namespace": record.namespace,
                "key": record.key,
                "version": record.version,
                "content_sha256": record.content_sha256,
                "provenance_id": record.completion_provenance_id,
            }
        )
        self._vector_store.upsert(str(record.memory_id), record.content, metadata)
