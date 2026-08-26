"""Canonical provider-neutral memory domain and service contracts."""

from __future__ import annotations


def _run_as_script() -> None:
    """Handle direct execution of this package file."""
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)

    from src.memory.service import MemoryService  # noqa: F401

    print("Artemis City memory package initialized successfully.")
    raise SystemExit(0)


if __name__ == "__main__" and not __package__:
    _run_as_script()

from .models import (  # noqa: E402
    ClaimDisposition,
    LedgerState,
    LedgerWrite,
    MemoryError,
    MemoryIdempotencyConflict,
    MemoryLedgerUnavailable,
    MemoryNamespaceConflict,
    MemoryRecord,
    MemoryValidationError,
    MemoryWriteCommand,
    MemoryWriteReceipt,
    ProjectionState,
    WriteDisposition,
)
from .ports import MemoryLedger, MemoryProjection, ProjectionClaim  # noqa: E402
from .service import MemoryService  # noqa: E402

__all__ = [
    "ClaimDisposition",
    "LedgerState",
    "LedgerWrite",
    "MemoryError",
    "MemoryIdempotencyConflict",
    "MemoryLedger",
    "MemoryLedgerUnavailable",
    "MemoryNamespaceConflict",
    "MemoryProjection",
    "MemoryRecord",
    "MemoryService",
    "MemoryValidationError",
    "MemoryWriteCommand",
    "MemoryWriteReceipt",
    "ProjectionClaim",
    "ProjectionState",
    "WriteDisposition",
]
