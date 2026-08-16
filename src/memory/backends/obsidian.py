"""Deterministic Obsidian materialization for canonical memory versions."""

from __future__ import annotations

import json
import ntpath
from pathlib import PurePosixPath

from src.memory.models import MemoryRecord
from src.obsidian_integration.manager import ObsidianManager


def _validated_projection_path(value: str) -> str:
    """Preserve one exact safe vault-relative POSIX path."""
    raw_parts = value.split("/") if isinstance(value, str) else []
    path = PurePosixPath(value)
    drive, _ = ntpath.splitdrive(value)
    if (
        not value
        or drive
        or path.is_absolute()
        or "\\" in value
        or "\x00" in value
        or any(part in {"", ".", ".."} or not part.strip() for part in raw_parts)
    ):
        raise ValueError("projection path must be a safe relative POSIX path")
    return path.as_posix()


def _quoted(value: str | None) -> str:
    """Serialize a nullable string as a YAML-compatible JSON scalar."""
    return json.dumps(value, ensure_ascii=False)


def _render_note(record: MemoryRecord) -> str:
    """Render stable identifiers before the committed content bytes."""
    return (
        "---\n"
        f"record_id: {_quoted(record.record_id)}\n"
        f"memory_id: {_quoted(record.memory_id)}\n"
        f"namespace: {_quoted(record.namespace)}\n"
        f"key: {_quoted(record.key)}\n"
        f"version: {record.version}\n"
        f"content_sha256: {_quoted(record.content_sha256)}\n"
        f"provenance_id: {_quoted(record.completion_provenance_id)}\n"
        "---\n\n"
        f"{record.content}"
    )


class ObsidianMemoryProjection:
    """Project immutable memory records into human-readable vault notes."""

    name = "obsidian"

    def __init__(self, manager: ObsidianManager) -> None:
        self._manager = manager

    def project(self, record: MemoryRecord) -> None:
        """Overwrite the record's exact validated projection path once."""
        projection_path = _validated_projection_path(record.projection_path)
        self._manager.write_note(projection_path, _render_note(record))
