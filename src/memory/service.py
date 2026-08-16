"""Canonical write-through orchestration over ledger and projection ports."""

from __future__ import annotations

from collections.abc import Iterable

from .models import (
    ClaimDisposition,
    LedgerWrite,
    MemoryLedgerUnavailable,
    MemoryRecord,
    MemoryValidationError,
    MemoryWriteCommand,
    MemoryWriteReceipt,
    ProjectionState,
    validate_key,
    validate_namespace,
    validate_required_text,
)
from .ports import MemoryLedger, MemoryProjection, ProjectionClaim

PROJECTION_FAILURE_CODE = "projection_failed"
RETRYABLE_PROJECTION_STATES = {ProjectionState.PENDING, ProjectionState.FAILED}


class MemoryService:
    """Coordinate durable memory writes before external materialization."""

    def __init__(
        self, ledger: MemoryLedger, projections: Iterable[MemoryProjection]
    ) -> None:
        self._ledger = ledger
        self._projections: dict[str, MemoryProjection] = {}
        for projection in projections:
            validate_required_text(projection.name, "projection name")
            if projection.name in self._projections:
                raise MemoryValidationError(
                    f"duplicate projection adapter: {projection.name}"
                )
            self._projections[projection.name] = projection

    def write(self, command: MemoryWriteCommand) -> MemoryWriteReceipt:
        """Write once to the ledger, then deliver retryable projections."""
        self._validate_projection_adapters(command)
        ledger_write = self._ledger.write_version(command)
        self._deliver_requested_projections(command, ledger_write)
        final_states = self._ledger.projection_status(
            command.namespace, ledger_write.record.record_id
        )
        if final_states is None:
            raise MemoryLedgerUnavailable("written memory record no longer exists")
        return MemoryWriteReceipt(
            record=ledger_write.record,
            disposition=ledger_write.disposition,
            ledger_state=ledger_write.ledger_state,
            projection_states=final_states,
            summary=self._summary(ledger_write, final_states),
        )

    def read(self, namespace: str, key: str) -> MemoryRecord | None:
        """Read the current exact memory from one namespace."""
        validate_namespace(namespace)
        validate_key(key)
        return self._ledger.read(namespace, key)

    def search(self, namespace: str, query: str, limit: int) -> list[MemoryRecord]:
        """Search one namespace with a bounded result count."""
        validate_namespace(namespace)
        validate_required_text(query, "query")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise MemoryValidationError("search limit must be between 1 and 100")
        return self._ledger.search(namespace, query, limit)

    def projection_status(
        self, namespace: str, record_id: str
    ) -> dict[str, ProjectionState] | None:
        """Return states, or ``None`` when the namespaced record is absent."""
        validate_namespace(namespace)
        validate_required_text(record_id, "record_id")
        return self._ledger.projection_status(namespace, record_id)

    def _validate_projection_adapters(self, command: MemoryWriteCommand) -> None:
        unknown = [
            name
            for name in command.requested_projections
            if name not in self._projections
        ]
        if unknown:
            names = ", ".join(unknown)
            raise MemoryValidationError(f"unknown projection: {names}")

    def _deliver_requested_projections(
        self, command: MemoryWriteCommand, ledger_write: LedgerWrite
    ) -> None:
        for target in command.requested_projections:
            state = ledger_write.projection_states.get(target)
            if state not in RETRYABLE_PROJECTION_STATES:
                continue
            with self._ledger.claim_projection(
                ledger_write.record.record_id, target
            ) as claim:
                self._transition_claim(claim, self._projections[target])

    @staticmethod
    def _transition_claim(claim: ProjectionClaim, projection: MemoryProjection) -> None:
        if claim.disposition is ClaimDisposition.TERMINAL:
            return
        if claim.disposition is ClaimDisposition.SUPERSEDED:
            claim.mark_skipped()
            return

        try:
            projection.project(claim.record)
        # Projection ports may raise provider-specific errors. The durable,
        # sanitized outbox transition is the observable failure record.
        except Exception:  # noqa: BLE001
            claim.mark_failed(PROJECTION_FAILURE_CODE)
        else:
            claim.mark_succeeded()

    @staticmethod
    def _summary(
        ledger_write: LedgerWrite,
        projection_states: dict[str, ProjectionState],
    ) -> str:
        record = ledger_write.record
        states = ", ".join(
            f"{name}={state.value}" for name, state in projection_states.items()
        )
        projection_summary = states or "no projections"
        return (
            f"Memory {record.memory_id} version {record.version} "
            f"{ledger_write.disposition.value}; {projection_summary}."
        )
