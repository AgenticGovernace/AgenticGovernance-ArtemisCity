"""Contract tests for the transactional PostgreSQL memory store."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event, Lock
from typing import Any, Self

import pytest

from src.integration.sql_memory_store import (
    IdempotencyConflictError,
    MemoryStoreError,
    PostgresMemoryStore,
)


class FakePostgresConnection:
    """Stateful transaction fake that accepts the store's PostgreSQL SQL."""

    def __init__(
        self, *, fail_outbox_insert: bool = False, canonical_contract: bool = False
    ) -> None:
        self.fail_outbox_insert = fail_outbox_insert
        self.canonical_contract = canonical_contract
        self.records: dict[str, dict[str, Any]] = {}
        self.heads: dict[str, dict[str, Any]] = {}
        self.outbox: dict[str, dict[str, Any]] = {}
        self.executed_queries: list[str] = []
        self._snapshot: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = (
            None
        )

    def __enter__(self) -> Self:
        self._snapshot = deepcopy((self.records, self.heads, self.outbox))
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is not None and self._snapshot is not None:
            self.records, self.heads, self.outbox = self._snapshot
        self._snapshot = None
        return False

    def cursor(self) -> FakePostgresCursor:
        return FakePostgresCursor(self)


class FakePostgresCursor:
    """Small stateful cursor for the memory-store query boundary."""

    def __init__(self, connection: FakePostgresConnection) -> None:
        self.connection = connection
        self._row: dict[str, Any] | None = None
        self._rows: list[dict[str, Any]] = []
        self.rowcount = -1

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False

    def execute(self, query: str, parameters: tuple[object, ...] | None = None) -> None:
        normalized = " ".join(query.split()).lower()
        values = parameters or ()
        self.connection.executed_queries.append(normalized)
        self._row = None
        self._rows = []
        self.rowcount = -1

        if "memory:contract-version" in normalized:
            self._row = {"canonical_contract": self.connection.canonical_contract}
        elif "pg_advisory_xact_lock" in normalized:
            self._row = {"pg_advisory_xact_lock": None}
        elif (
            "from artemis.memory_records" in normalized
            and "idempotency_key" in normalized
        ):
            key = str(values[0])
            self._row = next(
                (
                    record
                    for record in self.connection.records.values()
                    if record["idempotency_key"] == key
                ),
                None,
            )
        elif "from artemis.memory_heads" in normalized and "for update" in normalized:
            self._row = self.connection.heads.get(str(values[0]))
        elif "insert into artemis.memory_records" in normalized:
            record = {
                "record_id": values[0],
                "memory_id": values[1],
                "relative_path": values[2],
                "revision": values[3],
                "idempotency_key": values[4],
                "content": values[5],
                "content_sha256": values[6],
                "metadata": values[7],
                "provenance_id": values[8],
                "source_agent": values[9],
                "created_at": datetime(2026, 8, 16, tzinfo=UTC),
            }
            self.connection.records[str(record["record_id"])] = record
            self._row = record
        elif "insert into artemis.memory_heads" in normalized:
            self.connection.heads[str(values[0])] = {
                "relative_path": values[0],
                "memory_id": values[1],
                "current_record_id": values[2],
                "current_revision": values[3],
            }
        elif "update artemis.memory_heads" in normalized:
            head = self.connection.heads[str(values[2])]
            head.update(current_record_id=values[0], current_revision=values[1])
        elif "memory:supersede-obsolete" in normalized:
            self.rowcount = 0
            for event in self.connection.outbox.values():
                if (
                    event["relative_path"] == values[0]
                    and event["revision"] < values[1]
                    and event["status"] in {"pending", "processing"}
                ):
                    event["status"] = "delivered"
                    event["last_error_code"] = "superseded_by_newer_revision"
                    self.rowcount += 1
        elif "insert into artemis.memory_outbox" in normalized:
            if self.connection.fail_outbox_insert:
                raise RuntimeError("outbox unavailable")
            assert "status" in normalized
            assert "'pending'" in normalized
            self.connection.outbox[str(values[0])] = {
                "event_id": values[0],
                "record_id": values[1],
                "memory_id": values[2],
                "relative_path": values[3],
                "revision": values[4],
                "target": "obsidian",
                "status": "pending",
            }
        elif "select event_id, status from artemis.memory_outbox" in normalized:
            self._row = next(
                (
                    event
                    for event in self.connection.outbox.values()
                    if event["record_id"] == values[0]
                ),
                None,
            )
        elif (
            "from artemis.memory_heads as h" in normalized
            and "join artemis.memory_records as r" in normalized
            and "order by h.relative_path" in normalized
        ):
            has_prefix = "where h.relative_path like" in normalized
            prefix = str(values[0]).removesuffix("%") if has_prefix else ""
            rows = [
                self.connection.records[str(head["current_record_id"])]
                for path, head in sorted(self.connection.heads.items())
                if path.startswith(prefix)
            ]
            limit_index = 1 if has_prefix else 0
            self._rows = (
                rows
                if " limit " not in normalized
                else rows[: int(values[limit_index])]
            )
        elif (
            "from artemis.memory_heads" in normalized
            and "join artemis.memory_records" in normalized
        ):
            head = self.connection.heads.get(str(values[0]))
            self._row = (
                self.connection.records.get(str(head["current_record_id"]))
                if head
                else None
            )
        elif "memory:legacy-delivered" in normalized:
            event = self.connection.outbox.get(str(values[0]))
            self.rowcount = int(event is not None)
            if event is not None:
                event["status"] = "delivered"
        elif "memory:legacy-failed" in normalized:
            event = self.connection.outbox.get(str(values[1]))
            self.rowcount = int(event is not None)
            if event is not None and event["status"] in {
                "pending",
                "processing",
                "failed",
            }:
                event["status"] = "pending"
                event["last_error_code"] = values[0]
        elif (
            "from artemis.memory_outbox" in normalized
            and "where o.status in ('pending', 'failed')" in normalized
        ):
            self._rows = [
                {
                    **self.connection.records[str(event["record_id"])],
                    "event_id": event["event_id"],
                    "status": event["status"],
                }
                for event in self.connection.outbox.values()
                if event["status"] in {"pending", "failed"}
            ][: int(values[0])]
        else:  # pragma: no cover - protects the fake from unsupported query changes.
            raise AssertionError(f"Unexpected SQL: {query}")

    def fetchone(self) -> dict[str, Any] | None:
        return self._row

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class UniqueViolation(RuntimeError):
    """A minimal PostgreSQL unique-constraint error fixture."""

    pgcode = "23505"


class ConcurrentFakeDatabase:
    """Shared state for controlled concurrent store transactions."""

    def __init__(self, *, race_on_idempotency: bool = False) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.heads: dict[str, dict[str, Any]] = {}
        self.outbox: dict[str, dict[str, Any]] = {}
        self.advisory_locks: dict[str, Lock] = {}
        self.advisory_locks_guard = Lock()
        self.head_read_barrier = Barrier(2)
        self.idempotency_lookup_barrier = Barrier(2) if race_on_idempotency else None
        self.record_insert_lock = Lock()
        self.first_write_committed = Event()
        self.race_on_idempotency = race_on_idempotency
        self.idempotency_lookups = 0
        self.unique_race_triggered = False

    def connection(self) -> ConcurrentFakeConnection:
        """Create a connection facade for one transaction."""
        return ConcurrentFakeConnection(self)


class ConcurrentFakeConnection(FakePostgresConnection):
    """Connection fake that supports transaction-scoped advisory path locks."""

    def __init__(self, database: ConcurrentFakeDatabase) -> None:
        super().__init__()
        self.database = database
        self.records = database.records
        self.heads = database.heads
        self.outbox = database.outbox
        self.advisory_locks: list[Lock] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            self.database.first_write_committed.set()
        for lock in reversed(self.advisory_locks):
            lock.release()
        self.advisory_locks = []
        return False

    def cursor(self) -> ConcurrentFakeCursor:
        return ConcurrentFakeCursor(self)


class ConcurrentFakeCursor(FakePostgresCursor):
    """Cursor fake that exposes races the store must close."""

    connection: ConcurrentFakeConnection

    def execute(self, query: str, parameters: tuple[object, ...] | None = None) -> None:
        normalized = " ".join(query.split()).lower()
        values = parameters or ()
        database = self.connection.database

        if "pg_advisory_xact_lock" in normalized:
            path = str(values[0])
            with database.advisory_locks_guard:
                lock = database.advisory_locks.setdefault(path, Lock())
            lock.acquire()
            self.connection.advisory_locks.append(lock)
            self._row = {"pg_advisory_xact_lock": None}
            return

        if (
            "from artemis.memory_records" in normalized
            and "idempotency_key" in normalized
        ):
            database.idempotency_lookups += 1
            if database.race_on_idempotency and database.idempotency_lookups <= 2:
                assert database.idempotency_lookup_barrier is not None
                key = str(values[0])
                self._row = next(
                    (
                        record
                        for record in database.records.values()
                        if record["idempotency_key"] == key
                    ),
                    None,
                )
                database.idempotency_lookup_barrier.wait(timeout=2)
                return

        if (
            "from artemis.memory_heads" in normalized
            and "for update" in normalized
            and not self.connection.advisory_locks
        ):
            database.head_read_barrier.wait(timeout=2)

        if (
            database.race_on_idempotency
            and "insert into artemis.memory_records" in normalized
        ):
            with database.record_insert_lock:
                existing = next(
                    (
                        record
                        for record in database.records.values()
                        if record["idempotency_key"] == values[4]
                    ),
                    None,
                )
                if existing is not None:
                    database.unique_race_triggered = True
                else:
                    return super().execute(query, parameters)
            database.first_write_committed.wait(timeout=2)
            raise UniqueViolation("duplicate key value violates unique idempotency_key")

        super().execute(query, parameters)


def test_concurrent_first_writes_to_one_new_path_are_sequenced() -> None:
    """The new-path lock prevents competing revision-one head inserts."""
    database = ConcurrentFakeDatabase()
    store = PostgresMemoryStore(database.connection)

    def stage(idempotency_key: str, content: str) -> Any:
        return store.stage_write(
            relative_path="Notes/concurrent.md",
            content=content,
            metadata=None,
            idempotency_key=idempotency_key,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(
            executor.map(
                lambda arguments: stage(*arguments),
                [
                    ("concurrent-new-1", "First write."),
                    ("concurrent-new-2", "Second write."),
                ],
            )
        )

    assert sorted(receipt.revision.revision for receipt in receipts) == [1, 2]
    assert len({receipt.revision.memory_id for receipt in receipts}) == 1
    assert database.heads["Notes/concurrent.md"]["current_revision"] == 2


def test_concurrent_idempotency_race_returns_winning_receipt() -> None:
    """A unique-key loser re-reads the winner instead of surfacing storage failure."""
    database = ConcurrentFakeDatabase(race_on_idempotency=True)
    store = PostgresMemoryStore(database.connection)

    def stage(relative_path: str) -> Any:
        return store.stage_write(
            relative_path=relative_path,
            content="Idempotent payload.",
            metadata=None,
            idempotency_key="shared-concurrent-key",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(stage, ["Notes/shared.md", "Notes/shared.md"]))

    assert {receipt.duplicate for receipt in receipts} == {False, True}
    assert len({receipt.revision.record_id for receipt in receipts}) == 1
    assert database.unique_race_triggered is True
    assert database.idempotency_lookups >= 3


def make_store(
    *, fail_outbox_insert: bool = False
) -> tuple[PostgresMemoryStore, FakePostgresConnection]:
    """Return a store and inspectable fake connection for one test."""
    connection = FakePostgresConnection(fail_outbox_insert=fail_outbox_insert)
    return PostgresMemoryStore(lambda: connection), connection


def test_factory_owned_connections_are_closed_after_each_operation():
    """A short-lived runtime connection is closed after its transaction ends."""

    class ClosingConnection(FakePostgresConnection):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    connection = ClosingConnection()
    store = PostgresMemoryStore(lambda: connection, close_connections=True)

    assert store.get_current("notes/missing.md") is None
    assert connection.close_calls == 1


def test_driver_failure_exposes_only_sanitized_storage_error() -> None:
    """A driver message containing a DSN is not chained through the store boundary."""
    fake_dsn = "postgresql://operator:secret@fake-host/db"

    def fail_connection():
        raise OSError(f"could not connect to {fake_dsn}")

    store = PostgresMemoryStore(fail_connection)

    with pytest.raises(MemoryStoreError) as error:
        store.get_current("Notes/safe.md")

    assert error.value.code == "MEMORY_STORAGE_UNAVAILABLE"
    assert str(error.value) == "failed to read canonical memory revision"
    assert error.value.__cause__ is None
    assert fake_dsn not in str(error.value)


def test_stage_write_commits_revision_head_and_outbox_together() -> None:
    """A committed write persists one revision, path head, and pending event."""
    store, connection = make_store()

    receipt = store.stage_write(
        relative_path="Notes/mission.md",
        content="Artemis remembers.",
        metadata={"kind": "memory"},
        idempotency_key="mission-write-1",
    )

    assert receipt.revision.relative_path == "Notes/mission.md"
    assert receipt.revision.revision == 1
    assert receipt.revision.metadata == {"kind": "memory"}
    assert (
        receipt.revision.content_sha256
        == "418283b5134a55970c04812dfb58505875e7d9ed642296085bdac52dd03ca90f"
    )
    assert receipt.projection_status == "pending"
    assert receipt.duplicate is False
    assert (
        len(connection.records) == len(connection.heads) == len(connection.outbox) == 1
    )


def test_stage_write_rolls_back_all_state_when_outbox_insert_fails() -> None:
    """An outbox failure does not leave a record or head committed."""
    store, connection = make_store(fail_outbox_insert=True)

    with pytest.raises(MemoryStoreError):
        store.stage_write(
            relative_path="Notes/mission.md",
            content="Artemis remembers.",
            metadata=None,
            idempotency_key="mission-write-1",
        )

    assert connection.records == {}
    assert connection.heads == {}
    assert connection.outbox == {}


def test_replaying_idempotency_key_returns_original_receipt() -> None:
    """An identical idempotency replay returns the first receipt without a new event."""
    store, connection = make_store()
    original = store.stage_write(
        relative_path="Notes/mission.md",
        content="Artemis remembers.",
        metadata={"kind": "memory"},
        idempotency_key="mission-write-1",
    )

    replay = store.stage_write(
        relative_path="Notes/mission.md",
        content="Artemis remembers.",
        metadata={"kind": "different-but-idempotent"},
        idempotency_key="mission-write-1",
    )

    assert replay.revision.record_id == original.revision.record_id
    assert replay.event_id == original.event_id
    assert replay.duplicate is True
    assert len(connection.records) == len(connection.outbox) == 1


def test_reusing_idempotency_key_for_different_content_raises_conflict() -> None:
    """A key cannot be reused for a changed committed request."""
    store, connection = make_store()
    store.stage_write(
        relative_path="Notes/mission.md",
        content="Artemis remembers.",
        metadata=None,
        idempotency_key="mission-write-1",
    )

    with pytest.raises(IdempotencyConflictError):
        store.stage_write(
            relative_path="Notes/mission.md",
            content="Artemis forgets.",
            metadata=None,
            idempotency_key="mission-write-1",
        )


@pytest.mark.parametrize(
    "relative_path",
    [
        "Notes/./alias.md",
        "Notes//alias.md",
        "Notes/alias.md/",
        r"Notes\alias.md",
        "Notes/cafe\u0301.md",
    ],
)
def test_stage_write_rejects_noncanonical_path_aliases(relative_path: str) -> None:
    """One projected filesystem target must have exactly one SQL path identity."""
    store, connection = make_store()

    with pytest.raises(ValueError, match="canonical"):
        store.stage_write(
            relative_path=relative_path,
            content="alias",
            metadata=None,
            idempotency_key=f"alias-{relative_path}",
        )

    assert connection.records == {}


@pytest.mark.parametrize(
    "relative_path", ["Notes", "x.md/child.md", ".foo.md/child.md"]
)
def test_stage_write_rejects_file_directory_namespace_conflicts(
    relative_path: str,
) -> None:
    """Canonical records are leaves and cannot make a file an ancestor folder."""
    store, connection = make_store()

    with pytest.raises(ValueError, match="leaf"):
        store.stage_write(
            relative_path=relative_path,
            content="namespace conflict",
            metadata=None,
            idempotency_key=f"namespace-{relative_path}",
        )

    assert connection.records == {}


def test_stage_write_allows_hidden_directory_without_file_suffix() -> None:
    """A leading-dot directory is valid when its remaining name has no suffix."""
    store, connection = make_store()

    receipt = store.stage_write(
        relative_path=".artemis/context/state.json",
        content="{}",
        metadata=None,
        idempotency_key="hidden-context-1",
    )

    assert receipt.revision.relative_path == ".artemis/context/state.json"
    assert len(connection.records) == 1


@pytest.mark.parametrize("metadata", [{"bad": object()}, {"score": float("nan")}])
def test_stage_write_rejects_non_strict_json_before_transaction(metadata) -> None:
    """Caller metadata errors are validation failures, never storage outages."""
    store, connection = make_store()

    with pytest.raises(ValueError, match="strict JSON"):
        store.stage_write(
            relative_path="Notes/metadata.md",
            content="metadata",
            metadata=metadata,
            idempotency_key="metadata-1",
        )

    assert connection.executed_queries == []


def test_stage_write_rejects_invalid_provenance_uuid_before_transaction() -> None:
    """Invalid provenance is rejected before a PostgreSQL UUID cast."""
    store, connection = make_store()

    with pytest.raises(ValueError, match="provenance_id"):
        store.stage_write(
            relative_path="Notes/provenance.md",
            content="provenance",
            metadata=None,
            idempotency_key="provenance-1",
            provenance_id="not-a-uuid",
        )

    assert connection.executed_queries == []


def test_get_current_returns_committed_revision_while_projection_pending() -> None:
    """The current read comes from committed SQL even before projection delivery."""
    store, _ = make_store()
    receipt = store.stage_write(
        relative_path="Notes/mission.md",
        content="Artemis remembers.",
        metadata=None,
        idempotency_key="mission-write-1",
    )

    current = store.get_current("Notes/mission.md")

    assert current is not None
    assert current.record_id == receipt.revision.record_id
    assert current.content == "Artemis remembers."


def test_list_current_returns_only_committed_heads_under_prefix() -> None:
    """Canonical directory discovery is independent of Obsidian projection state."""
    store, connection = make_store()
    for path, key in (
        ("Agent Inputs/pending.md", "pending-1"),
        ("Agent Inputs/nested/second.md", "pending-2"),
        ("Agent Outputs/report.md", "output-1"),
    ):
        store.stage_write(
            relative_path=path,
            content=path,
            metadata={"path": path},
            idempotency_key=key,
        )

    current = store.list_current("Agent Inputs")

    assert [revision.relative_path for revision in current] == [
        "Agent Inputs/nested/second.md",
        "Agent Inputs/pending.md",
    ]
    assert " limit " not in connection.executed_queries[-1]


def test_outbox_updates_change_pending_receipts() -> None:
    """Delivery updates remove events from pending work while failures preserve them."""
    store, _ = make_store()
    receipt = store.stage_write(
        relative_path="Notes/mission.md",
        content="Artemis remembers.",
        metadata=None,
        idempotency_key="mission-write-1",
    )

    store.mark_projection_failed(receipt.event_id, "obsidian-unavailable")
    pending = store.list_pending()
    store.mark_delivered(receipt.event_id)

    assert [(item.event_id, item.projection_status) for item in pending] == [
        (receipt.event_id, "pending")
    ]
    assert store.list_pending() == []


def test_delivered_outbox_event_cannot_be_reopened_by_late_failure() -> None:
    """A post-delivery exception cannot turn completed projection work pending."""
    store, _ = make_store()
    receipt = store.stage_write(
        relative_path="Notes/delivered.md",
        content="Delivered.",
        metadata=None,
        idempotency_key="delivered-1",
    )
    store.mark_delivered(receipt.event_id)

    store.mark_projection_failed(receipt.event_id, "late_observability_failure")

    assert store.list_pending() == []


def test_newer_revision_supersedes_older_pending_projection_event() -> None:
    """Only the current path head remains actionable projection work."""
    store, connection = make_store()
    first = store.stage_write(
        relative_path="Notes/current-only.md",
        content="revision one",
        metadata=None,
        idempotency_key="current-only-1",
    )
    second = store.stage_write(
        relative_path="Notes/current-only.md",
        content="revision two",
        metadata=None,
        idempotency_key="current-only-2",
    )

    assert connection.outbox[first.event_id]["status"] == "delivered"
    assert connection.outbox[first.event_id]["last_error_code"] == (
        "superseded_by_newer_revision"
    )
    assert [receipt.event_id for receipt in store.list_pending()] == [second.event_id]


def test_v0001_outbox_methods_keep_pending_and_delivered_states() -> None:
    """The stable v0001 API preserves its pending and delivered vocabulary."""
    store, connection = make_store()
    receipt = store.stage_write(
        relative_path="Notes/upgrade.md",
        content="Before migration.",
        metadata=None,
        idempotency_key="upgrade-write-1",
    )
    store.mark_projection_failed(receipt.event_id, "projection_failed")
    pending = store.list_pending()
    assert connection.outbox[receipt.event_id]["status"] == "pending"
    assert [(item.event_id, item.projection_status) for item in pending] == [
        (receipt.event_id, "pending")
    ]

    store.mark_delivered(receipt.event_id)
    assert connection.outbox[receipt.event_id]["status"] == "delivered"
    assert store.list_pending() == []


def test_default_stage_write_does_not_auto_activate_partial_enhanced_schema() -> None:
    """A stray enhanced column cannot silently change the v0001 write contract."""
    connection = FakePostgresConnection(canonical_contract=True)
    store = PostgresMemoryStore(lambda: connection)

    receipt = store.stage_write(
        relative_path="Notes/default-v0001.md",
        content="Use the stable v0001 contract.",
        metadata=None,
        idempotency_key="default-v0001-1",
        source_agent="Agent_0",
    )

    assert receipt.revision.source_agent == "Agent_0"
    assert not any(
        "memory:contract-version" in query for query in connection.executed_queries
    )


@pytest.mark.parametrize("method_name", ["mark_delivered", "mark_projection_failed"])
def test_outbox_updates_reject_missing_event(method_name: str) -> None:
    """An acknowledgement that updates no outbox row is a storage failure."""
    store, _ = make_store()
    method = getattr(store, method_name)
    arguments = (
        ("missing-event", "projection_failed")
        if method_name.endswith("failed")
        else ("missing-event",)
    )

    with pytest.raises(MemoryStoreError) as error:
        method(*arguments)

    assert error.value.code == "MEMORY_STORAGE_UNAVAILABLE"
    assert str(error.value) == "projection event does not exist"


def test_projection_guard_holds_the_same_path_lock_as_stage_write() -> None:
    """A writer cannot advance the head while a projection guard is held."""
    database = ConcurrentFakeDatabase()
    store = PostgresMemoryStore(database.connection)
    first = store.stage_write(
        relative_path="Notes/guarded.md",
        content="revision one",
        metadata=None,
        idempotency_key="guarded-1",
    )
    guard_entered = Event()
    allow_guard_exit = Event()
    second_finished = Event()

    def hold_projection() -> None:
        with store.projection_guard("Notes/guarded.md") as current:
            assert current is not None
            assert current.record_id == first.revision.record_id
            guard_entered.set()
            assert allow_guard_exit.wait(timeout=2)

    def write_newer() -> None:
        assert guard_entered.wait(timeout=2)
        store.stage_write(
            relative_path="Notes/guarded.md",
            content="revision two",
            metadata=None,
            idempotency_key="guarded-2",
        )
        second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        guarded = executor.submit(hold_projection)
        writer = executor.submit(write_newer)
        assert guard_entered.wait(timeout=2)
        assert second_finished.wait(timeout=0.05) is False
        allow_guard_exit.set()
        guarded.result(timeout=2)
        writer.result(timeout=2)

    assert second_finished.is_set()
    assert store.get_current("Notes/guarded.md").content == "revision two"


def test_v0001_migration_is_atomic_versioned_and_exact_path_bound() -> None:
    """The static migration declares its no-partial-apply safety contract."""
    migration = (
        Path(__file__).parents[2] / "db/migrations/0001_memory_write_through.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(migration.split()).lower()

    assert normalized.startswith("begin;")
    assert normalized.endswith("commit;")
    assert "pg_advisory_xact_lock" in normalized
    assert "artemis.schema_migrations" in normalized
    assert "0001_memory_write_through" in normalized
    assert (
        "raise exception 'migration 0001_memory_write_through is already applied'"
        in normalized
    )
    assert "errcode = 'p0001'" in normalized
    assert "unique (record_id, memory_id, revision, relative_path)" in normalized
    assert "current_record_id, memory_id, current_revision, relative_path" in normalized
    assert (
        normalized.count(
            "references artemis.memory_records (record_id, memory_id, revision, relative_path)"
        )
        == 2
    )
    assert "left(relative_path, 1) not in ('/', e'\\\\')" in normalized
    assert "position(e'\\\\' in relative_path) = 0" in normalized
    assert "relative_path not like '%//%'" in normalized
    assert "relative_path !~ '(^|/)\\.(/|$)'" in normalized
    assert "right(relative_path, 1) <> '/'" in normalized
    assert "relative_path ~ '(^|/)[^/]+\\.[^/]+$'" in normalized
    assert "relative_path !~ '(^|/)\\.*[^/.][^/]*\\.[^/]+/'" in normalized
    assert "relative_path = normalize(relative_path, nfc)" in normalized
    assert "on artemis.memory_heads (lower(relative_path))" in normalized
    assert normalized.index("insert into artemis.schema_migrations") < normalized.index(
        "create table artemis.memory_records"
    )
