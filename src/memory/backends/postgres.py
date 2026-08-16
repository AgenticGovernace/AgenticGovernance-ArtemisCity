"""Thin domain adapter over the enhanced PostgreSQL memory store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from src.integration.sql_memory_store import (
    CanonicalIdempotencyConflict,
    CanonicalMemoryRevision,
    CanonicalNamespaceConflict,
    CanonicalProjectionClaim,
    MemoryStoreError,
    PostgresMemoryStore,
)
from src.memory.models import (
    ClaimDisposition,
    LedgerWrite,
    MemoryIdempotencyConflict,
    MemoryLedgerUnavailable,
    MemoryNamespaceConflict,
    MemoryRecord,
    MemoryWriteCommand,
    ProjectionState,
    WriteDisposition,
)


class PostgresProjectionClaim:
    """Domain view of a lock-held enhanced-store projection claim."""

    def __init__(self, claim: CanonicalProjectionClaim) -> None:
        self._claim = claim
        self.record = _domain_record(claim.revision)
        self.target = claim.target
        self.disposition = ClaimDisposition(claim.disposition)

    def mark_succeeded(self) -> None:
        """Persist successful projection delivery in the held transaction."""
        self._claim.mark_succeeded()

    def mark_failed(self, error_code: str) -> None:
        """Persist a retryable projection failure in the held transaction."""
        self._claim.mark_failed(error_code)

    def mark_skipped(self) -> None:
        """Persist a superseded projection as terminal skipped work."""
        self._claim.mark_skipped()


class PostgresMemoryLedger:
    """Implement the canonical memory ledger port through one SQL store."""

    def __init__(self, store: PostgresMemoryStore) -> None:
        self._store = store

    def write_version(self, command: MemoryWriteCommand) -> LedgerWrite:
        """Create or replay one canonical memory version transactionally."""
        assert command.projection_path is not None
        try:
            stored = self._store.stage_canonical_write(
                namespace=command.namespace,
                key=command.key,
                relative_path=command.projection_path,
                content=command.content,
                metadata=command.metadata,
                idempotency_key=command.idempotency_key,
                principal_id=command.principal_id,
                parent_provenance_id=command.parent_provenance_id,
                requested_projections=command.requested_projections,
            )
        except CanonicalIdempotencyConflict as exc:
            raise MemoryIdempotencyConflict(str(exc)) from exc
        except CanonicalNamespaceConflict as exc:
            raise MemoryNamespaceConflict(str(exc)) from exc
        except MemoryStoreError as exc:
            raise MemoryLedgerUnavailable(str(exc)) from exc
        return LedgerWrite(
            record=_domain_record(stored.revision),
            disposition=(
                WriteDisposition.REPLAYED
                if stored.replayed
                else WriteDisposition.CREATED
            ),
            projection_states={
                target: ProjectionState(state)
                for target, state in stored.projection_statuses.items()
            },
            projection_event_ids=stored.projection_event_ids,
        )

    @contextmanager
    def claim_projection(
        self, record_id: str, projection: str
    ) -> Iterator[PostgresProjectionClaim]:
        """Hold the store transaction and logical lock across projection work."""
        try:
            with self._store.claim_canonical_projection(record_id, projection) as claim:
                yield PostgresProjectionClaim(claim)
        except MemoryStoreError as exc:
            raise MemoryLedgerUnavailable(str(exc)) from exc

    def read(self, namespace: str, key: str) -> MemoryRecord | None:
        """Return the current exact record within one namespace."""
        try:
            stored = self._store.read_canonical(namespace, key)
        except MemoryStoreError as exc:
            raise MemoryLedgerUnavailable(str(exc)) from exc
        return _domain_record(stored) if stored is not None else None

    def search(self, namespace: str, query: str, limit: int) -> list[MemoryRecord]:
        """Search current record text within one namespace."""
        try:
            rows = self._store.search_canonical(namespace, query, limit)
        except MemoryStoreError as exc:
            raise MemoryLedgerUnavailable(str(exc)) from exc
        return [_domain_record(row) for row in rows]

    def projection_status(
        self, namespace: str, record_id: str
    ) -> dict[str, ProjectionState] | None:
        """Return states, or ``None`` when the namespaced record is absent."""
        try:
            states = self._store.canonical_projection_status(namespace, record_id)
        except MemoryStoreError as exc:
            raise MemoryLedgerUnavailable(str(exc)) from exc
        if states is None:
            return None
        return {target: ProjectionState(state) for target, state in states.items()}


def _domain_record(stored: CanonicalMemoryRevision) -> MemoryRecord:
    """Map one enhanced-store snapshot into the immutable domain contract."""
    return MemoryRecord(
        record_id=stored.record_id,
        memory_id=stored.memory_id,
        namespace=stored.namespace,
        key=stored.key,
        projection_path=stored.relative_path,
        version=stored.revision,
        content=stored.content,
        content_sha256=stored.content_sha256,
        metadata=stored.metadata,
        idempotency_key=stored.idempotency_key,
        principal_id=stored.principal_id,
        parent_provenance_id=stored.parent_provenance_id,
        completion_provenance_id=stored.completion_provenance_id,
        created_at=stored.created_at,
    )
