"""Provider-neutral ports used by the canonical memory service."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from .models import (
    ClaimDisposition,
    LedgerWrite,
    MemoryRecord,
    MemoryWriteCommand,
    ProjectionState,
)


class ProjectionClaim(Protocol):
    """Locked, version-specific projection decision owned by a ledger."""

    record: MemoryRecord
    target: str
    disposition: ClaimDisposition

    def mark_succeeded(self) -> None:
        """Persist successful delivery while the ledger claim is held."""
        ...

    def mark_failed(self, error_code: str) -> None:
        """Persist a retryable delivery failure using a sanitized code."""
        ...

    def mark_skipped(self) -> None:
        """Persist that a superseded version must never be delivered."""
        ...


class MemoryLedger(Protocol):
    """Canonical version, idempotency, and projection-outbox boundary."""

    def write_version(self, command: MemoryWriteCommand) -> LedgerWrite:
        """Create or replay a durable memory version transactionally."""
        ...

    def claim_projection(
        self, record_id: str, projection: str
    ) -> AbstractContextManager[ProjectionClaim]:
        """Lock and classify a version-specific projection event."""
        ...

    def read(self, namespace: str, key: str) -> MemoryRecord | None:
        """Return the current exact record within a namespace."""
        ...

    def search(self, namespace: str, query: str, limit: int) -> list[MemoryRecord]:
        """Search current records within a namespace."""
        ...

    def projection_status(
        self, namespace: str, record_id: str
    ) -> dict[str, ProjectionState]:
        """Return version-specific projection states within a namespace."""
        ...


class MemoryProjection(Protocol):
    """External materialization of immutable memory versions."""

    name: str

    def project(self, record: MemoryRecord) -> None:
        """Materialize a deterministic representation of the record."""
        ...
