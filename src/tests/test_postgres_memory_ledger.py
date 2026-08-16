"""Behavioral contracts for the PostgreSQL canonical memory ledger."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import psycopg2
import pytest

from src.integration.sql_memory_store import PostgresMemoryStore
from src.memory.backends.postgres import PostgresMemoryLedger
from src.memory.models import (ClaimDisposition, MemoryIdempotencyConflict,
                               MemoryLedgerUnavailable,
                               MemoryNamespaceConflict, MemoryRecord,
                               MemoryWriteCommand, ProjectionState,
                               WriteDisposition)
from src.memory.service import MemoryService


def command(**overrides: object) -> MemoryWriteCommand:
    """Build one literal governed command for adapter tests."""
    values: dict[str, object] = {
        "namespace": "agents",
        "key": "research/result",
        "content": "version one",
        "metadata": {"task": "T-500"},
        "idempotency_key": "request-500",
        "principal_id": "agent-7",
        "parent_provenance_id": "parent-500",
        "requested_projections": ("obsidian", "vector"),
        "projection_path": "Memory/agents/research/result.md",
    }
    values.update(overrides)
    return MemoryWriteCommand(**values)  # type: ignore[arg-type]


class LedgerDatabase:
    """Stateful DB-API boundary with real transactions and advisory locks."""

    def __init__(
        self, *, fail_on: str | None = None, race_on_idempotency: bool = False
    ) -> None:
        self.fail_on = fail_on
        self.records: dict[str, dict[str, Any]] = {}
        self.heads: dict[str, dict[str, Any]] = {}
        self.provenance: dict[str, dict[str, Any]] = {}
        self.outbox: dict[str, dict[str, Any]] = {}
        self.commit_count = 0
        self.rollback_count = 0
        self.statement_classes: list[str] = []
        self.lock_tokens: list[str] = []
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._idempotency_barrier = (
            threading.Barrier(2) if race_on_idempotency else None
        )
        self._idempotency_lookups = 0
        self._idempotency_guard = threading.Lock()

    def connection(self) -> LedgerConnection:
        return LedgerConnection(self)

    def lock_for(self, token: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(token, threading.Lock())

    def seed_legacy_path(self, relative_path: str) -> str:
        """Seed the exact shape produced by migration 0002 for a 0001 row."""
        record_id = "00000000-0000-0000-0000-000000000091"
        memory_id = "00000000-0000-0000-0000-000000000092"
        self.records[record_id] = {
            "record_id": record_id,
            "memory_id": memory_id,
            "relative_path": relative_path,
            "revision": 1,
            "idempotency_key": "legacy-request",
            "content": "legacy version",
            "content_sha256": "4" * 64,
            "metadata": {},
            "provenance_id": None,
            "source_agent": None,
            "created_at": datetime(2026, 8, 15, tzinfo=UTC),
            "namespace": "legacy",
            "memory_key": relative_path,
            "principal_id": None,
            "parent_provenance_id": None,
            "requested_projections": ("obsidian",),
        }
        self.heads[relative_path] = {
            "relative_path": relative_path,
            "memory_id": memory_id,
            "current_record_id": record_id,
            "current_revision": 1,
            "namespace": "legacy",
            "memory_key": relative_path,
        }
        event_id = "00000000-0000-0000-0000-000000000093"
        self.outbox[event_id] = {
            "event_id": event_id,
            "record_id": record_id,
            "memory_id": memory_id,
            "relative_path": relative_path,
            "revision": 1,
            "target": "obsidian",
            "status": "pending",
            "last_error_code": None,
        }
        return memory_id


class LedgerConnection:
    """One transaction over shared test state."""

    def __init__(self, database: LedgerDatabase) -> None:
        self.database = database
        self._snapshot: tuple[dict[str, Any], ...] | None = None
        self._held_locks: list[threading.Lock] = []
        self._mutated = False

    def __enter__(self) -> Self:
        self._snapshot = deepcopy(
            (
                self.database.records,
                self.database.heads,
                self.database.provenance,
                self.database.outbox,
            )
        )
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            self.database.commit_count += 1
        elif self._mutated:
            assert self._snapshot is not None
            (
                self.database.records,
                self.database.heads,
                self.database.provenance,
                self.database.outbox,
            ) = self._snapshot
        if exc_type is not None:
            self.database.rollback_count += 1
        for lock in reversed(self._held_locks):
            lock.release()
        self._held_locks.clear()
        return False

    def cursor(self) -> LedgerCursor:
        return LedgerCursor(self)

    def close(self) -> None:
        pass


class LedgerCursor:
    """Cursor implementing the semantic SQL markers emitted by the store."""

    def __init__(self, connection: LedgerConnection) -> None:
        self.connection = connection
        self._row: dict[str, Any] | None = None
        self._rows: list[dict[str, Any]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False

    def execute(self, query: str, parameters: Sequence[object] | None = None) -> None:
        marker = query.split("*/", 1)[0].removeprefix("/*").strip()
        values = tuple(parameters or ())
        database = self.connection.database
        database.statement_classes.append(marker)
        self._row = None
        self._rows = []

        if marker == "memory:lock":
            token = str(values[0])
            lock = database.lock_for(token)
            lock.acquire()
            self.connection._held_locks.append(lock)
            database.lock_tokens.append(token)
            return
        if marker == "memory:contract-version":
            self._row = {"canonical_contract": True}
            return
        if marker == "memory:idempotency":
            namespace, idempotency_key = map(str, values)
            self._row = next(
                (
                    row
                    for row in database.records.values()
                    if row["namespace"] == namespace
                    and row["idempotency_key"] == idempotency_key
                ),
                None,
            )
            with database._idempotency_guard:
                database._idempotency_lookups += 1
                lookup_number = database._idempotency_lookups
            if database._idempotency_barrier is not None and lookup_number <= 2:
                database._idempotency_barrier.wait(timeout=2)
            return
        if marker == "memory:path-head":
            self._row = database.heads.get(str(values[0]))
            return
        if marker == "memory:record-insert":
            self._fail_if_requested("record")
            keys = (
                "record_id",
                "memory_id",
                "relative_path",
                "revision",
                "idempotency_key",
                "content",
                "content_sha256",
                "metadata",
                "provenance_id",
                "source_agent",
                "namespace",
                "memory_key",
                "principal_id",
                "parent_provenance_id",
                "requested_projections",
            )
            row = dict(zip(keys, values, strict=True))
            row["metadata"] = json.loads(str(row["metadata"]))
            row["requested_projections"] = tuple(
                json.loads(str(row["requested_projections"]))
            )
            row["created_at"] = datetime(2026, 8, 16, 12, tzinfo=UTC)
            database.records[str(row["record_id"])] = row
            self.connection._mutated = True
            self._row = row
            return
        if marker in {"memory:head-insert", "memory:head-update"}:
            self._fail_if_requested("head")
            relative_path, memory_id, record_id, revision, namespace, key = values
            database.heads[str(relative_path)] = {
                "relative_path": relative_path,
                "memory_id": memory_id,
                "current_record_id": record_id,
                "current_revision": revision,
                "namespace": namespace,
                "memory_key": key,
            }
            self.connection._mutated = True
            return
        if marker == "memory:provenance-insert":
            self._fail_if_requested("provenance")
            record_id, provenance_id, parent_id, principal_id = values
            database.provenance[str(record_id)] = {
                "record_id": record_id,
                "provenance_id": provenance_id,
                "parent_provenance_id": parent_id,
                "principal_id": principal_id,
                "event_type": "memory.write",
            }
            self.connection._mutated = True
            return
        if marker == "memory:outbox-insert":
            self._fail_if_requested("outbox")
            event_id, record_id, memory_id, path, revision, target = values
            database.outbox[str(event_id)] = {
                "event_id": event_id,
                "record_id": record_id,
                "memory_id": memory_id,
                "relative_path": path,
                "revision": revision,
                "target": target,
                "status": "pending",
                "last_error_code": None,
            }
            self.connection._mutated = True
            return
        if marker == "memory:events":
            record_id = str(values[0])
            self._rows = [
                event
                for event in database.outbox.values()
                if event["record_id"] == record_id
            ]
            return
        if marker == "memory:completion":
            self._row = database.provenance.get(str(values[0]))
            return
        if marker == "memory:record-by-id":
            self._row = database.records.get(str(values[0]))
            return
        if marker == "memory:claim-state":
            record_id, target = map(str, values)
            record = database.records.get(record_id)
            event = next(
                (
                    row
                    for row in database.outbox.values()
                    if row["record_id"] == record_id and row["target"] == target
                ),
                None,
            )
            head = database.heads.get(str(record["relative_path"])) if record else None
            self._row = (
                {**record, **event, "current_record_id": head["current_record_id"]}
                if record and event and head
                else None
            )
            return
        if marker == "memory:claim-mark":
            state, error_code = values[:2]
            record_id, target = values[-2:]
            event = next(
                row
                for row in database.outbox.values()
                if row["record_id"] == record_id and row["target"] == target
            )
            event["status"] = state
            event["last_error_code"] = error_code
            self.connection._mutated = True
            return
        if marker == "memory:read":
            namespace, key = map(str, values)
            head = next(
                (
                    row
                    for row in database.heads.values()
                    if row["namespace"] == namespace and row["memory_key"] == key
                ),
                None,
            )
            self._row = (
                database.records[str(head["current_record_id"])] if head else None
            )
            return
        if marker == "memory:search":
            namespace, query_text, limit = values
            current_ids = {
                str(head["current_record_id"])
                for head in database.heads.values()
                if head["namespace"] == namespace
            }
            self._rows = [
                row
                for row in reversed(list(database.records.values()))
                if str(row["record_id"]) in current_ids
                and str(query_text).casefold() in str(row["content"]).casefold()
            ][: int(limit)]
            return
        if marker == "memory:status":
            namespace, record_id = map(str, values)
            record = database.records.get(record_id)
            if record is None or record["namespace"] != namespace:
                self._rows = []
            else:
                self._rows = [
                    row
                    for row in database.outbox.values()
                    if row["record_id"] == record_id
                ]
                if not self._rows:
                    self._rows = [
                        {"record_id": record_id, "target": None, "status": None}
                    ]
            return
        raise AssertionError(f"Unexpected SQL marker {marker!r}: {query}")

    def _fail_if_requested(self, statement_class: str) -> None:
        if self.connection.database.fail_on == statement_class:
            raise RuntimeError(f"forced {statement_class} failure")

    def fetchone(self) -> dict[str, Any] | None:
        return self._row

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


def make_ledger(
    database: LedgerDatabase | None = None,
) -> tuple[PostgresMemoryLedger, LedgerDatabase]:
    """Construct the adapter over its real enhanced SQL store."""
    database = database or LedgerDatabase()
    return PostgresMemoryLedger(PostgresMemoryStore(database.connection)), database


def test_write_commits_record_head_provenance_and_all_outbox_events_once() -> None:
    """One successful canonical transaction persists every durable write artifact."""
    ledger, database = make_ledger()

    result = ledger.write_version(command())

    assert result.disposition is WriteDisposition.CREATED
    assert result.projection_states == {
        "obsidian": ProjectionState.PENDING,
        "vector": ProjectionState.PENDING,
    }
    assert len(database.records) == 1
    assert len(database.heads) == 1
    assert len(database.provenance) == 1
    assert len(database.outbox) == 2
    assert database.commit_count == 1
    provenance = database.provenance[result.record.record_id]
    assert provenance["provenance_id"] == result.record.completion_provenance_id
    assert (
        database.records[result.record.record_id]["provenance_id"]
        == provenance["provenance_id"]
    )


def test_legacy_stage_write_uses_enhanced_transaction_after_0002() -> None:
    """The legacy import adopts canonical schema while preserving its receipt API."""
    database = LedgerDatabase()
    store = PostgresMemoryStore(
        database.connection, enable_legacy_canonical_adapter=True
    )
    parent_provenance_id = "11111111-1111-4111-8111-111111111111"

    receipt = store.stage_write(
        relative_path="Notes/compatible.md",
        content="Compatible write.",
        metadata={"source": "legacy-api"},
        idempotency_key="legacy-compatible-1",
        provenance_id=parent_provenance_id,
        source_agent="legacy-agent",
    )

    stored = database.records[receipt.revision.record_id]
    assert (stored["namespace"], stored["memory_key"]) == (
        "legacy",
        "Notes/compatible.md",
    )
    assert stored["source_agent"] == "legacy-agent"
    assert stored["parent_provenance_id"] == parent_provenance_id
    assert stored["provenance_id"] == receipt.revision.provenance_id
    assert database.provenance[receipt.revision.record_id]["provenance_id"] == (
        receipt.revision.provenance_id
    )
    assert receipt.event_id in database.outbox
    assert receipt.projection_status == "pending"

    replay = store.stage_write(
        relative_path="Notes/compatible.md",
        content="Compatible write.",
        metadata={"source": "ignored-on-replay"},
        idempotency_key="legacy-compatible-1",
        provenance_id=parent_provenance_id,
        source_agent="legacy-agent",
    )
    assert replay.duplicate is True
    assert replay.revision.provenance_id == receipt.revision.provenance_id


@pytest.mark.parametrize("statement_class", ["record", "head", "provenance", "outbox"])
def test_every_write_statement_class_rolls_back_the_whole_transaction(
    statement_class: str,
) -> None:
    """Any canonical write statement failure leaves no partial durable artifacts."""
    ledger, database = make_ledger(LedgerDatabase(fail_on=statement_class))

    with pytest.raises(Exception, match="canonical memory write"):
        ledger.write_version(command())

    assert database.records == {}
    assert database.heads == {}
    assert database.provenance == {}
    assert database.outbox == {}
    assert database.commit_count == 0
    assert database.rollback_count == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"content": "changed"},
        {"key": "research/other"},
        {"projection_path": "Memory/agents/research/other.md"},
        {"requested_projections": ("obsidian",)},
    ],
)
def test_namespace_idempotency_replay_rejects_changed_bound_input(
    overrides: dict[str, object],
) -> None:
    """A namespace key cannot replay changed content, path, key, or projections."""
    ledger, database = make_ledger()
    original = ledger.write_version(command())

    with pytest.raises(MemoryIdempotencyConflict):
        ledger.write_version(command(**overrides))

    assert list(database.records) == [original.record.record_id]


def test_idempotency_is_scoped_by_namespace_and_replay_preserves_completion() -> None:
    """Exact replay reuses completion evidence while another namespace may reuse the key."""
    ledger, database = make_ledger()
    original = ledger.write_version(command())

    replay = ledger.write_version(command(metadata={"ignored": "on replay"}))
    other = ledger.write_version(
        command(
            namespace="teams",
            key="research/result",
            projection_path="Memory/teams/research/result.md",
        )
    )

    assert replay.disposition is WriteDisposition.REPLAYED
    assert replay.record.record_id == original.record.record_id
    assert (
        replay.record.completion_provenance_id
        == original.record.completion_provenance_id
    )
    assert other.record.record_id != original.record.record_id
    assert len(database.records) == 2


@pytest.mark.parametrize("corruption", ["missing", "extra"])
def test_replay_requires_exact_durable_projection_evidence(corruption: str) -> None:
    """Replay fails closed when event IDs/status keys differ from request evidence."""
    ledger, database = make_ledger()
    original = ledger.write_version(command())
    if corruption == "missing":
        event_id = original.projection_event_ids["vector"]
        del database.outbox[event_id]
    else:
        event_id = "00000000-0000-0000-0000-000000000077"
        database.outbox[event_id] = {
            "event_id": event_id,
            "record_id": original.record.record_id,
            "memory_id": original.record.memory_id,
            "relative_path": original.record.projection_path,
            "revision": original.record.version,
            "target": "unexpected",
            "status": "pending",
            "last_error_code": None,
        }

    with pytest.raises(MemoryLedgerUnavailable, match="projection evidence"):
        ledger.write_version(command())


@pytest.mark.parametrize("corruption", ["missing", "mismatch"])
def test_replay_requires_matching_completion_provenance(corruption: str) -> None:
    """Replay never claims completion lineage without its governed durable row."""
    ledger, database = make_ledger()
    original = ledger.write_version(command())
    if corruption == "missing":
        del database.provenance[original.record.record_id]
    else:
        database.provenance[original.record.record_id][
            "provenance_id"
        ] = "00000000-0000-0000-0000-000000000078"

    with pytest.raises(MemoryLedgerUnavailable, match="completion provenance"):
        ledger.write_version(command())


def test_version_allocation_uses_one_namespace_key_advisory_lock() -> None:
    """Two writes for one logical key allocate sequential versions and one memory ID."""
    ledger, database = make_ledger()
    first = ledger.write_version(command())
    second = ledger.write_version(
        command(content="version two", idempotency_key="request-501")
    )

    assert (first.record.version, second.record.version) == (1, 2)
    assert first.record.memory_id == second.record.memory_id
    assert database.lock_tokens.count("logical:agents:research/result") == 2
    assert database.statement_classes.index(
        "memory:lock"
    ) < database.statement_classes.index("memory:path-head")


def test_claim_classifies_and_service_owned_transitions_persist_under_lock() -> None:
    """Claims classify stale, retryable, and terminal events without implicit mutation."""
    ledger, database = make_ledger()
    first = ledger.write_version(command(requested_projections=("obsidian",)))
    second = ledger.write_version(
        command(
            content="version two",
            idempotency_key="request-501",
            requested_projections=("obsidian",),
        )
    )
    token = database.lock_tokens[-1]

    with ledger.claim_projection(first.record.record_id, "obsidian") as stale:
        assert stale.disposition is ClaimDisposition.SUPERSEDED
        assert ledger.projection_status("agents", first.record.record_id) == {
            "obsidian": ProjectionState.PENDING
        }
        assert database.lock_for(token).locked()
        stale.mark_skipped()
    assert ledger.projection_status("agents", first.record.record_id) == {
        "obsidian": ProjectionState.SKIPPED
    }

    with ledger.claim_projection(second.record.record_id, "obsidian") as current:
        assert current.disposition is ClaimDisposition.DELIVER
        current.mark_failed("projection_failed")
    with ledger.claim_projection(second.record.record_id, "obsidian") as retry:
        assert retry.disposition is ClaimDisposition.DELIVER
        retry.mark_succeeded()
    with ledger.claim_projection(second.record.record_id, "obsidian") as terminal:
        assert terminal.disposition is ClaimDisposition.TERMINAL


class RecordingProjection:
    """Thread-safe external projection count used by replay serialization."""

    name = "obsidian"

    def __init__(self) -> None:
        self.record_ids: list[str] = []
        self._guard = threading.Lock()

    def project(self, record: MemoryRecord) -> None:
        with self._guard:
            self.record_ids.append(record.record_id)


def test_concurrent_replay_calls_projection_adapter_once() -> None:
    """Two service retries serialize claim classification around one adapter call."""
    ledger, _ = make_ledger()
    projection = RecordingProjection()
    service = MemoryService(ledger, [projection])
    write = command(requested_projections=("obsidian",))

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(lambda _: service.write(write), range(2)))

    assert len({receipt.record.record_id for receipt in receipts}) == 1
    assert len(projection.record_ids) == 1


def test_concurrent_cross_key_idempotency_race_returns_typed_conflict() -> None:
    """One namespace idempotency lock resolves different logical-key contenders."""
    ledger, database = make_ledger(LedgerDatabase(race_on_idempotency=True))

    def write(key: str) -> str:
        try:
            result = ledger.write_version(
                command(key=key, projection_path=f"Memory/agents/{key}.md")
            )
        except MemoryIdempotencyConflict:
            return "conflict"
        return result.disposition.value

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write, ("alpha", "beta")))

    assert sorted(outcomes) == ["conflict", "created"]
    assert len(database.records) == 1
    assert database.lock_tokens.count("idempotency:agents:request-500") == 2


def test_read_search_and_status_are_namespace_and_record_scoped() -> None:
    """Exact reads, text search, and immutable status never cross namespaces."""
    ledger, _ = make_ledger()
    agents = ledger.write_version(
        command(requested_projections=("obsidian",), content="shared signal")
    )
    teams = ledger.write_version(
        command(
            namespace="teams",
            projection_path="Memory/teams/research/result.md",
            requested_projections=("vector",),
            content="shared signal",
        )
    )

    assert ledger.read("agents", "research/result") == agents.record
    assert ledger.search("agents", "SIGNAL", 10) == [agents.record]
    assert ledger.search("teams", "signal", 10) == [teams.record]
    assert ledger.projection_status("teams", agents.record.record_id) is None
    assert ledger.projection_status("agents", agents.record.record_id) == {
        "obsidian": ProjectionState.PENDING
    }

    no_projection = ledger.write_version(
        command(
            key="without-projection",
            projection_path="Memory/agents/without-projection.md",
            idempotency_key="without-projection",
            requested_projections=(),
        )
    )
    assert ledger.projection_status("agents", no_projection.record.record_id) == {}


def test_legacy_path_is_adopted_only_by_its_migrated_identity() -> None:
    """The exact legacy identity advances while another identity gets a typed conflict."""
    database = LedgerDatabase()
    memory_id = database.seed_legacy_path("Notes/legacy.md")
    ledger, _ = make_ledger(database)

    adopted = ledger.write_version(
        command(
            namespace="legacy",
            key="Notes/legacy.md",
            projection_path="Notes/legacy.md",
            idempotency_key="legacy-request-2",
            requested_projections=("obsidian",),
        )
    )
    assert adopted.record.version == 2
    assert adopted.record.memory_id == memory_id

    with pytest.raises(MemoryNamespaceConflict):
        ledger.write_version(
            command(
                namespace="agents",
                key="legacy-copy",
                projection_path="Notes/legacy.md",
                idempotency_key="conflicting-path",
                requested_projections=("obsidian",),
            )
        )


def _database_identity(database_url: str, label: str) -> tuple[str, str, str]:
    """Parse a non-secret host/port/database identity without connecting."""
    try:
        values = psycopg2.extensions.parse_dsn(database_url)
    except (psycopg2.Error, TypeError, ValueError):
        raise RuntimeError(f"{label} database identity is invalid") from None
    host = str(values.get("host") or "").casefold().rstrip(".")
    port = str(values.get("port") or "5432")
    database_name = str(values.get("dbname") or "")
    if not host or not database_name:
        raise RuntimeError(f"{label} database identity is invalid")
    return host, port, database_name


@contextmanager
def disposable_postgres_connection() -> Iterator[Any]:
    """Connect only to the explicitly configured disposable test database."""
    database_url = os.environ.get("ARTEMIS_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "ARTEMIS_TEST_DATABASE_URL is absent; live Neon/PostgreSQL syntax is not claimed"
        )
    if os.environ.get("ARTEMIS_TEST_DATABASE_ALLOW_SCHEMA_RESET") != "1":
        pytest.skip(
            "ARTEMIS_TEST_DATABASE_ALLOW_SCHEMA_RESET=1 is required for live schema mutation"
        )
    test_identity = _database_identity(database_url, "test")
    expected_host = os.environ.get("ARTEMIS_TEST_DATABASE_EXPECTED_HOST")
    expected_name = os.environ.get("ARTEMIS_TEST_DATABASE_EXPECTED_NAME")
    normalized_expected_host = (
        expected_host.casefold().rstrip(".") if expected_host else None
    )
    if (
        normalized_expected_host is None
        or not expected_name
        or test_identity[0] != normalized_expected_host
        or test_identity[2] != expected_name
    ):
        raise RuntimeError(
            "test database identity does not match explicit expected host and name"
        )
    runtime_url = os.environ.get("ARTEMIS_MEMORY_DATABASE_URL")
    if runtime_url and test_identity == _database_identity(runtime_url, "runtime"):
        raise RuntimeError(
            "test database identity must differ from runtime memory database"
        )
    connection = psycopg2.connect(database_url)
    try:
        yield connection
    finally:
        connection.close()


def test_configured_live_dsn_requires_explicit_schema_reset_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Merely configuring a test DSN cannot authorize schema destruction."""
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_URL", "postgresql://test/db")
    monkeypatch.delenv("ARTEMIS_TEST_DATABASE_ALLOW_SCHEMA_RESET", raising=False)
    connected = False

    def reject_connect(_database_url: str) -> object:
        nonlocal connected
        connected = True
        raise AssertionError("connection must not be attempted")

    monkeypatch.setattr(psycopg2, "connect", reject_connect)
    with (
        pytest.raises(pytest.skip.Exception, match="ALLOW_SCHEMA_RESET"),
        disposable_postgres_connection(),
    ):
        pass
    assert connected is False


def test_live_dsn_rejects_the_configured_memory_database_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The optional destructive test cannot target the runtime memory database."""
    database_url = "postgresql://runtime/memory"
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_URL", database_url)
    monkeypatch.setenv("ARTEMIS_MEMORY_DATABASE_URL", database_url)
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_ALLOW_SCHEMA_RESET", "1")
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_EXPECTED_HOST", "runtime")
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_EXPECTED_NAME", "memory")
    connected = False

    def reject_connect(_database_url: str) -> object:
        nonlocal connected
        connected = True
        raise AssertionError("connection must not be attempted")

    monkeypatch.setattr(psycopg2, "connect", reject_connect)
    with (
        pytest.raises(RuntimeError, match="must differ"),
        disposable_postgres_connection(),
    ):
        pass
    assert connected is False


@pytest.mark.parametrize(
    "missing_name",
    ["ARTEMIS_TEST_DATABASE_EXPECTED_HOST", "ARTEMIS_TEST_DATABASE_EXPECTED_NAME"],
)
def test_live_dsn_requires_explicit_expected_database_identity_before_connect(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    """Reset opt-in is insufficient without an exact expected host/database binding."""
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_URL", "postgresql://db.test/task5")
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_ALLOW_SCHEMA_RESET", "1")
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_EXPECTED_HOST", "db.test")
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_EXPECTED_NAME", "task5")
    monkeypatch.delenv(missing_name)
    connected = False

    def reject_connect(_database_url: str) -> object:
        nonlocal connected
        connected = True
        raise AssertionError("connection must not be attempted")

    monkeypatch.setattr(psycopg2, "connect", reject_connect)
    with (
        pytest.raises(RuntimeError, match="expected host and name"),
        disposable_postgres_connection(),
    ):
        pass
    assert connected is False


def test_v0001_applies_and_repeat_guard_fails_closed_on_disposable_postgres() -> None:
    """Optional live proof covers the deployable v0001 migration by itself."""
    migration = (
        Path(__file__).parents[2]
        / "db"
        / "migrations"
        / "0001_memory_write_through.sql"
    ).read_text(encoding="utf-8")
    with disposable_postgres_connection() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS artemis CASCADE")
            cursor.execute(migration)
            cursor.execute(
                "SELECT version FROM artemis.schema_migrations "
                "WHERE version = '0001_memory_write_through'"
            )
            assert cursor.fetchone() == ("0001_memory_write_through",)
            with pytest.raises(psycopg2.errors.RaiseException) as error:
                cursor.execute(migration)
            assert error.value.pgcode == "P0001"
        connection.rollback()


@pytest.mark.parametrize(
    ("expected_host", "expected_name"),
    [("other.test", "task5"), ("db.test", "other")],
)
def test_live_dsn_rejects_mismatched_expected_identity_before_connect(
    monkeypatch: pytest.MonkeyPatch, expected_host: str, expected_name: str
) -> None:
    """A mismatched expected host or database prevents any connection attempt."""
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_URL", "postgresql://db.test/task5")
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_ALLOW_SCHEMA_RESET", "1")
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_EXPECTED_HOST", expected_host)
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_EXPECTED_NAME", expected_name)
    connected = False

    def reject_connect(_database_url: str) -> object:
        nonlocal connected
        connected = True
        raise AssertionError("connection must not be attempted")

    monkeypatch.setattr(psycopg2, "connect", reject_connect)
    with (
        pytest.raises(RuntimeError, match="expected host and name"),
        disposable_postgres_connection(),
    ):
        pass
    assert connected is False


def test_live_dsn_rejects_normalized_runtime_identity_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credentials and DSN spelling cannot disguise the runtime database identity."""
    monkeypatch.setenv(
        "ARTEMIS_TEST_DATABASE_URL",
        "postgresql://tester:secret@DB.EXAMPLE:5432/memory?sslmode=require",
    )
    monkeypatch.setenv(
        "ARTEMIS_MEMORY_DATABASE_URL",
        "host=db.example port=5432 dbname=memory user=runtime",
    )
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_ALLOW_SCHEMA_RESET", "1")
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_EXPECTED_HOST", "db.example")
    monkeypatch.setenv("ARTEMIS_TEST_DATABASE_EXPECTED_NAME", "memory")
    connected = False

    def reject_connect(_database_url: str) -> object:
        nonlocal connected
        connected = True
        raise AssertionError("connection must not be attempted")

    monkeypatch.setattr(psycopg2, "connect", reject_connect)
    with (
        pytest.raises(RuntimeError, match="must differ"),
        disposable_postgres_connection(),
    ):
        pass
    assert connected is False


def test_migrations_upgrade_populated_legacy_rows_on_disposable_postgres() -> None:
    """Optional live proof applies 0001 then evolves populated rows through 0002."""
    migrations = Path(__file__).parents[2] / "db" / "migrations"
    migration_0002 = migrations / "0002_memory_server_contract.sql"
    if not migration_0002.is_file():
        pytest.skip("0002 memory-server migration is not implemented")
    with (
        disposable_postgres_connection() as connection,
        connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("DROP SCHEMA IF EXISTS artemis CASCADE")
        cursor.execute((migrations / "0001_memory_write_through.sql").read_text())
        for number, status in enumerate(
            ("pending", "processing", "delivered", "dead"), start=1
        ):
            record_id = f"00000000-0000-0000-0000-{number:012d}"
            memory_id = f"10000000-0000-0000-0000-{number:012d}"
            event_id = f"20000000-0000-0000-0000-{number:012d}"
            path = f"Legacy/{number}.md"
            cursor.execute(
                "INSERT INTO artemis.memory_records "
                "(record_id, memory_id, relative_path, revision, idempotency_key, "
                "content, content_sha256) VALUES (%s, %s, %s, 1, %s, %s, %s)",
                (
                    record_id,
                    memory_id,
                    path,
                    f"key-{number}",
                    status,
                    str(number) * 64,
                ),
            )
            cursor.execute(
                "INSERT INTO artemis.memory_heads "
                "(relative_path, memory_id, current_record_id, current_revision) "
                "VALUES (%s, %s, %s, 1)",
                (path, memory_id, record_id),
            )
            cursor.execute(
                "INSERT INTO artemis.memory_outbox "
                "(event_id, record_id, memory_id, relative_path, revision, target, operation, status) "
                "VALUES (%s, %s, %s, %s, 1, 'obsidian', 'write', %s)",
                (event_id, record_id, memory_id, path, status),
            )
        cursor.execute(migration_0002.read_text(encoding="utf-8"))
        cursor.execute(
            "SELECT relative_path, namespace, memory_key, content, content_sha256 "
            "FROM artemis.memory_records ORDER BY relative_path"
        )
        rows = cursor.fetchall()
        assert rows[0] == (
            "Legacy/1.md",
            "legacy",
            "Legacy/1.md",
            "pending",
            "1" * 64,
        )
        cursor.execute(
            "SELECT status FROM artemis.memory_outbox ORDER BY relative_path"
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "pending",
            "pending",
            "succeeded",
            "skipped",
        ]
        with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
            cursor.execute(
                "UPDATE artemis.memory_records SET content = 'changed' "
                "WHERE relative_path = 'Legacy/1.md'"
            )

    database_url = os.environ["ARTEMIS_TEST_DATABASE_URL"]
    store = PostgresMemoryStore(
        lambda: psycopg2.connect(database_url), close_connections=True
    )
    ledger = PostgresMemoryLedger(store)
    first = ledger.write_version(
        command(requested_projections=("obsidian",), idempotency_key="live-v1")
    )
    second = ledger.write_version(
        command(
            requested_projections=("obsidian",),
            idempotency_key="live-v2",
            content="version two",
        )
    )
    replay = ledger.write_version(
        command(requested_projections=("obsidian",), idempotency_key="live-v1")
    )
    assert replay.record.record_id == first.record.record_id
    assert (
        replay.record.completion_provenance_id == first.record.completion_provenance_id
    )

    with ledger.claim_projection(first.record.record_id, "obsidian") as stale:
        assert stale.disposition is ClaimDisposition.SUPERSEDED
        stale.mark_skipped()
    assert ledger.projection_status("agents", first.record.record_id) == {
        "obsidian": ProjectionState.SKIPPED
    }

    adopted = ledger.write_version(
        command(
            namespace="legacy",
            key="Legacy/1.md",
            projection_path="Legacy/1.md",
            requested_projections=("obsidian",),
            idempotency_key="live-legacy-adopt",
        )
    )
    assert adopted.record.version == 2
    assert adopted.record.memory_id == "10000000-0000-0000-0000-000000000001"
    with pytest.raises(MemoryNamespaceConflict):
        ledger.write_version(
            command(
                namespace="agents",
                key="legacy-conflict",
                projection_path="Legacy/1.md",
                requested_projections=("obsidian",),
                idempotency_key="live-legacy-conflict",
            )
        )

    with (
        psycopg2.connect(database_url) as verification,
        verification.cursor() as cursor,
    ):
        created_ids = (
            first.record.record_id,
            second.record.record_id,
            adopted.record.record_id,
        )
        cursor.execute(
            "SELECT count(*) FROM artemis.memory_records "
            "WHERE record_id = ANY(%s::uuid[])",
            (list(created_ids),),
        )
        assert cursor.fetchone()[0] == 3
        cursor.execute(
            "SELECT count(*) FROM artemis.memory_completion_provenance "
            "WHERE record_id = ANY(%s::uuid[])",
            (list(created_ids),),
        )
        assert cursor.fetchone()[0] == 3
        cursor.execute(
            "SELECT record_id, target, status FROM artemis.memory_outbox "
            "WHERE record_id = ANY(%s::uuid[]) ORDER BY record_id, target",
            (list(created_ids),),
        )
        durable_events = cursor.fetchall()
        assert len(durable_events) == 3
        assert {
            (str(record_id), target, status)
            for record_id, target, status in durable_events
        } == {
            (first.record.record_id, "obsidian", "skipped"),
            (second.record.record_id, "obsidian", "pending"),
            (adopted.record.record_id, "obsidian", "pending"),
        }
        cursor.execute(
            "SELECT r.provenance_id, p.provenance_id "
            "FROM artemis.memory_records AS r "
            "JOIN artemis.memory_completion_provenance AS p USING (record_id) "
            "WHERE r.record_id = %s",
            (first.record.record_id,),
        )
        child_ids = cursor.fetchone()
        assert child_ids[0] == child_ids[1]
