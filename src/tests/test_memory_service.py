"""Behavioral tests for the canonical memory write-through service."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from src.memory.models import (
    ClaimDisposition,
    LedgerState,
    LedgerWrite,
    MemoryIdempotencyConflict,
    MemoryLedgerUnavailable,
    MemoryRecord,
    MemoryValidationError,
    MemoryWriteCommand,
    ProjectionState,
    WriteDisposition,
)
from src.memory.service import MemoryService


def valid_command(**overrides: object) -> MemoryWriteCommand:
    """Build a governed command with independently chosen test values."""
    values: dict[str, object] = {
        "namespace": "agents",
        "key": "research/result",
        "content": "version one",
        "metadata": {"task": "T-100"},
        "idempotency_key": "request-1",
        "principal_id": "agent-7",
        "parent_provenance_id": "prov-parent-7",
        "requested_projections": ("obsidian",),
    }
    values.update(overrides)
    return MemoryWriteCommand(**values)  # type: ignore[arg-type]


class RecordingProjection:
    """Projection adapter with an inspectable external representation."""

    def __init__(self, name: str, failing_content: set[str] | None = None) -> None:
        self.name = name
        self.failing_content = failing_content or set()
        self.record_ids: list[str] = []
        self.projected_by_path: dict[str, str] = {}

    def project(self, record: MemoryRecord) -> None:
        self.record_ids.append(record.record_id)
        if record.content in self.failing_content:
            raise RuntimeError("provider response included secret detail")
        self.projected_by_path[record.projection_path] = record.content


class InMemoryClaim:
    """Claim whose transitions mutate the durable test outbox."""

    def __init__(
        self,
        ledger: InMemoryLedger,
        record: MemoryRecord,
        target: str,
        disposition: ClaimDisposition,
    ) -> None:
        self._ledger = ledger
        self.record = record
        self.target = target
        self.disposition = disposition

    def mark_succeeded(self) -> None:
        self._ledger.set_projection_state(
            self.record.record_id, self.target, ProjectionState.SUCCEEDED
        )

    def mark_failed(self, error_code: str) -> None:
        self._ledger.failure_codes.append(error_code)
        self._ledger.set_projection_state(
            self.record.record_id, self.target, ProjectionState.FAILED
        )

    def mark_skipped(self) -> None:
        self._ledger.set_projection_state(
            self.record.record_id, self.target, ProjectionState.SKIPPED
        )


class InMemoryLedger:
    """Thread-safe ledger double implementing durable version/outbox behavior."""

    def __init__(
        self,
        *,
        fail_write: bool = False,
        write_barrier: threading.Barrier | None = None,
    ) -> None:
        self.fail_write = fail_write
        self.write_barrier = write_barrier
        self.write_calls = 0
        self.records: list[MemoryRecord] = []
        self.completion_provenance_ids: set[str] = set()
        self.claim_dispositions: list[ClaimDisposition] = []
        self.failure_codes: list[str] = []
        self.read_calls: list[tuple[str, str]] = []
        self.search_calls: list[tuple[str, str, int]] = []
        self.status_calls: list[tuple[str, str]] = []
        self._by_record_id: dict[str, MemoryRecord] = {}
        self._by_idempotency: dict[tuple[str, str], MemoryRecord] = {}
        self._heads: dict[tuple[str, str], str] = {}
        self._events: dict[tuple[str, str], ProjectionState] = {}
        self._event_ids: dict[tuple[str, str], str] = {}
        self._logical_locks: dict[tuple[str, str], threading.Lock] = {}
        self._state_lock = threading.Lock()

    def write_version(self, command: MemoryWriteCommand) -> LedgerWrite:
        self.write_calls += 1
        if self.fail_write:
            raise MemoryLedgerUnavailable("database unavailable")

        with self._state_lock:
            replay = self._by_idempotency.get(
                (command.namespace, command.idempotency_key)
            )
            if replay is not None:
                if replay.content != command.content or replay.key != command.key:
                    raise MemoryIdempotencyConflict(command.idempotency_key)
                result = self._ledger_write(replay, WriteDisposition.REPLAYED)
            else:
                result = self._create(command)

        if self.write_barrier is not None:
            self.write_barrier.wait(timeout=5)
        return result

    def _create(self, command: MemoryWriteCommand) -> LedgerWrite:
        logical_key = (command.namespace, command.key)
        previous_id = self._heads.get(logical_key)
        previous = self._by_record_id.get(previous_id) if previous_id else None
        record_number = len(self.records) + 1
        record_id = f"record-{record_number}"
        memory_id = previous.memory_id if previous else f"memory-{record_number}"
        version = previous.version + 1 if previous else 1
        child_id = f"completion-{record_id}"
        assert command.projection_path is not None
        record = MemoryRecord(
            record_id=record_id,
            memory_id=memory_id,
            namespace=command.namespace,
            key=command.key,
            projection_path=command.projection_path,
            version=version,
            content=command.content,
            content_sha256=hashlib.sha256(command.content.encode()).hexdigest(),
            metadata=dict(command.metadata),
            idempotency_key=command.idempotency_key,
            principal_id=command.principal_id,
            parent_provenance_id=command.parent_provenance_id,
            completion_provenance_id=child_id,
            created_at=datetime.now(UTC),
        )
        self.records.append(record)
        self.completion_provenance_ids.add(child_id)
        self._by_record_id[record_id] = record
        self._by_idempotency[(command.namespace, command.idempotency_key)] = record
        self._heads[logical_key] = record_id
        self._logical_locks.setdefault(logical_key, threading.Lock())
        for target in command.requested_projections:
            event_key = (record_id, target)
            self._events[event_key] = ProjectionState.PENDING
            self._event_ids[event_key] = f"event-{record_id}-{target}"
        return self._ledger_write(record, WriteDisposition.CREATED)

    def _ledger_write(
        self, record: MemoryRecord, disposition: WriteDisposition
    ) -> LedgerWrite:
        states = {
            target: state
            for (record_id, target), state in self._events.items()
            if record_id == record.record_id
        }
        event_ids = {
            target: event_id
            for (record_id, target), event_id in self._event_ids.items()
            if record_id == record.record_id
        }
        return LedgerWrite(
            record=record,
            disposition=disposition,
            projection_states=states,
            projection_event_ids=event_ids,
        )

    @contextmanager
    def claim_projection(
        self, record_id: str, projection: str
    ) -> Iterator[InMemoryClaim]:
        record = self._by_record_id[record_id]
        logical_key = (record.namespace, record.key)
        lock = self._logical_locks[logical_key]
        with lock:
            state = self._events[(record_id, projection)]
            if state in {ProjectionState.SUCCEEDED, ProjectionState.SKIPPED}:
                disposition = ClaimDisposition.TERMINAL
            elif self._heads[logical_key] != record_id:
                disposition = ClaimDisposition.SUPERSEDED
            else:
                disposition = ClaimDisposition.DELIVER
            self.claim_dispositions.append(disposition)
            yield InMemoryClaim(self, record, projection, disposition)

    def set_projection_state(
        self, record_id: str, target: str, state: ProjectionState
    ) -> None:
        self._events[(record_id, target)] = state

    def read(self, namespace: str, key: str) -> MemoryRecord | None:
        self.read_calls.append((namespace, key))
        record_id = self._heads.get((namespace, key))
        return self._by_record_id.get(record_id) if record_id else None

    def search(self, namespace: str, query: str, limit: int) -> list[MemoryRecord]:
        self.search_calls.append((namespace, query, limit))
        matches = [
            record
            for record in reversed(self.records)
            if record.namespace == namespace and query in record.content
        ]
        return matches[:limit]

    def projection_status(
        self, namespace: str, record_id: str
    ) -> dict[str, ProjectionState]:
        self.status_calls.append((namespace, record_id))
        record = self._by_record_id.get(record_id)
        if record is None or record.namespace != namespace:
            return {}
        return {
            target: state
            for (event_record_id, target), state in self._events.items()
            if event_record_id == record_id
        }

    @property
    def retryable_event_count(self) -> int:
        return sum(
            state in {ProjectionState.PENDING, ProjectionState.FAILED}
            for state in self._events.values()
        )


def test_memory_service_sql_failure_prevents_all_projection_writes() -> None:
    ledger = InMemoryLedger(fail_write=True)
    obsidian = RecordingProjection("obsidian")
    vector = RecordingProjection("vector")
    service = MemoryService(ledger, [obsidian, vector])

    with pytest.raises(MemoryLedgerUnavailable):
        service.write(valid_command(requested_projections=("obsidian", "vector")))

    assert obsidian.record_ids == []
    assert vector.record_ids == []


def test_memory_service_projection_failure_remains_durable_and_retryable() -> None:
    ledger = InMemoryLedger()
    obsidian = RecordingProjection("obsidian", failing_content={"version one"})
    service = MemoryService(ledger, [obsidian])

    receipt = service.write(valid_command())

    assert len(ledger.records) == 1
    assert receipt.ledger_state is LedgerState.SUCCEEDED
    assert receipt.projection_states == {"obsidian": ProjectionState.FAILED}
    assert ledger.retryable_event_count == 1
    assert ledger.failure_codes == ["projection_failed"]


def test_memory_service_idempotent_replay_reuses_record_and_provenance() -> None:
    ledger = InMemoryLedger()
    obsidian = RecordingProjection("obsidian")
    service = MemoryService(ledger, [obsidian])
    command = valid_command()

    first = service.write(command)
    second = service.write(command)

    assert second.disposition is WriteDisposition.REPLAYED
    assert (
        first.record.memory_id,
        first.record.version,
        first.record.content_sha256,
        first.record.completion_provenance_id,
    ) == (
        second.record.memory_id,
        second.record.version,
        second.record.content_sha256,
        second.record.completion_provenance_id,
    )
    assert first.record.record_id != first.record.memory_id
    assert len(ledger.records) == 1
    assert len(ledger.completion_provenance_ids) == 1


def test_memory_service_stale_replay_is_skipped_without_adapter_call() -> None:
    ledger = InMemoryLedger()
    obsidian = RecordingProjection("obsidian", failing_content={"version one"})
    service = MemoryService(ledger, [obsidian])
    version_one = valid_command()

    failed = service.write(version_one)
    obsidian.failing_content.clear()
    current = service.write(
        valid_command(content="version two", idempotency_key="request-2")
    )
    calls_before_replay = list(obsidian.record_ids)
    replay = service.write(version_one)

    assert failed.record.version == 1
    assert current.record.version == 2
    assert replay.projection_states == {"obsidian": ProjectionState.SKIPPED}
    assert ledger.claim_dispositions[-1] is ClaimDisposition.SUPERSEDED
    assert obsidian.record_ids == calls_before_replay
    assert obsidian.projected_by_path[current.record.projection_path] == "version two"


def test_memory_service_concurrent_replay_delivers_projection_once() -> None:
    barrier = threading.Barrier(2)
    ledger = InMemoryLedger(write_barrier=barrier)
    obsidian = RecordingProjection("obsidian")
    service = MemoryService(ledger, [obsidian])

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(service.write, valid_command()) for _ in range(2)]
        receipts = [future.result(timeout=5) for future in futures]

    assert len(receipts) == 2
    assert obsidian.record_ids == ["record-1"]
    assert sorted(ledger.claim_dispositions, key=lambda item: item.value) == [
        ClaimDisposition.DELIVER,
        ClaimDisposition.TERMINAL,
    ]


def test_memory_service_unknown_projection_rejects_before_ledger() -> None:
    ledger = InMemoryLedger()
    service = MemoryService(ledger, [RecordingProjection("obsidian")])

    with pytest.raises(MemoryValidationError, match="unknown projection"):
        service.write(valid_command(requested_projections=("vector",)))

    assert ledger.write_calls == 0
    assert ledger.records == []


def test_memory_service_read_is_namespace_scoped_and_returns_current_version() -> None:
    ledger = InMemoryLedger()
    service = MemoryService(ledger, [])
    service.write(
        valid_command(
            namespace="tenant-b",
            requested_projections=(),
            idempotency_key="tenant-b-1",
        )
    )
    current = service.write(
        valid_command(
            namespace="tenant-b",
            content="version two",
            requested_projections=(),
            idempotency_key="tenant-b-2",
        )
    )

    assert service.read("tenant-a", "research/result") is None
    assert service.read("tenant-b", "research/result") == current.record
    assert ledger.read_calls[-2:] == [
        ("tenant-a", "research/result"),
        ("tenant-b", "research/result"),
    ]


def test_memory_service_search_and_status_preserve_namespace_boundaries() -> None:
    ledger = InMemoryLedger()
    service = MemoryService(ledger, [])
    tenant_a = service.write(
        valid_command(
            namespace="tenant-a",
            content="shared needle",
            requested_projections=(),
            idempotency_key="tenant-a-1",
        )
    )
    service.write(
        valid_command(
            namespace="tenant-b",
            content="shared needle",
            requested_projections=(),
            idempotency_key="tenant-b-1",
        )
    )

    assert service.search("tenant-a", "needle", 10) == [tenant_a.record]
    assert service.projection_status("tenant-a", tenant_a.record.record_id) == {}
    assert service.projection_status("tenant-b", tenant_a.record.record_id) == {}
    assert ledger.search_calls[-1] == ("tenant-a", "needle", 10)
    assert ledger.status_calls[-2:] == [
        ("tenant-a", tenant_a.record.record_id),
        ("tenant-b", tenant_a.record.record_id),
    ]


@pytest.mark.parametrize("limit", [0, 101])
def test_memory_service_search_rejects_limit_outside_one_to_one_hundred(
    limit: int,
) -> None:
    ledger = InMemoryLedger()
    service = MemoryService(ledger, [])

    with pytest.raises(MemoryValidationError, match="between 1 and 100"):
        service.search("tenant-a", "needle", limit)

    assert ledger.search_calls == []


def test_memory_write_command_derives_safe_default_and_preserves_exact_path() -> None:
    derived = valid_command(key="daily.md")
    exact = valid_command(projection_path="Legacy Folder/Report Name.md")

    assert derived.projection_path == "Memory/agents/daily.md"
    assert exact.projection_path == "Legacy Folder/Report Name.md"


@pytest.mark.parametrize(
    "projection_path",
    [
        "/absolute.md",
        "folder//empty.md",
        "folder/./dot.md",
        "folder/../traversal.md",
        "folder\\..\\traversal.md",
    ],
)
def test_memory_write_command_rejects_unsafe_projection_paths(
    projection_path: str,
) -> None:
    with pytest.raises(MemoryValidationError):
        valid_command(projection_path=projection_path)


@pytest.mark.parametrize("field", ["principal_id", "parent_provenance_id"])
def test_memory_write_command_requires_governed_identity_fields(field: str) -> None:
    with pytest.raises(MemoryValidationError):
        valid_command(**{field: " "})
