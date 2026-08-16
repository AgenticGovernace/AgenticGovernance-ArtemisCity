"""PostgreSQL-backed canonical memory revisions and projection outbox."""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import PurePath
from typing import Protocol, Self


class CursorLike(Protocol):
    """Minimal cursor operations used by :class:`PostgresMemoryStore`."""

    rowcount: int

    def __enter__(self) -> Self: ...

    def __exit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> bool | None: ...

    def execute(
        self, query: str, parameters: Sequence[object] | None = None
    ) -> None: ...

    def fetchone(self) -> Mapping[str, object] | Sequence[object] | None: ...

    def fetchall(self) -> Sequence[Mapping[str, object] | Sequence[object]]: ...


class ConnectionLike(Protocol):
    """Minimal psycopg2-compatible connection operations."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> bool | None: ...

    def cursor(self) -> AbstractContextManager[CursorLike]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class MemoryRevision:
    """An immutable committed version of one vault-relative note."""

    record_id: str
    memory_id: str
    relative_path: str
    revision: int
    idempotency_key: str
    content: str
    content_sha256: str
    metadata: dict[str, object]
    provenance_id: str | None
    source_agent: str | None
    created_at: datetime


@dataclass(frozen=True)
class MemoryWriteReceipt:
    """The canonical revision and its corresponding projection work item."""

    revision: MemoryRevision
    event_id: str
    projection_status: str
    duplicate: bool


class MemoryStoreError(RuntimeError):
    """Raised when the canonical memory store cannot complete an operation."""

    code = "MEMORY_STORAGE_UNAVAILABLE"


class IdempotencyConflictError(MemoryStoreError):
    """Raised when an idempotency key is replayed with different content or path."""

    code = "MEMORY_IDEMPOTENCY_CONFLICT"


class CanonicalIdempotencyConflict(MemoryStoreError):
    """Raised when a namespace-scoped canonical request conflicts with its replay."""


class CanonicalNamespaceConflict(MemoryStoreError):
    """Raised when one relative path is already bound to another logical key."""


@dataclass(frozen=True)
class CanonicalMemoryRevision:
    """Storage representation of one enhanced immutable memory revision."""

    record_id: str
    memory_id: str
    namespace: str
    key: str
    relative_path: str
    revision: int
    content: str
    content_sha256: str
    metadata: dict[str, object]
    idempotency_key: str
    principal_id: str | None
    parent_provenance_id: str | None
    completion_provenance_id: str | None
    requested_projections: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class CanonicalMemoryWrite:
    """Enhanced store result with durable projection state and event evidence."""

    revision: CanonicalMemoryRevision
    replayed: bool
    projection_statuses: dict[str, str]
    projection_event_ids: dict[str, str]


class CanonicalProjectionClaim:
    """Lock-held projection decision whose transitions share the claim transaction."""

    def __init__(
        self,
        cursor: CursorLike,
        revision: CanonicalMemoryRevision,
        target: str,
        disposition: str,
    ) -> None:
        self.revision = revision
        self.target = target
        self.disposition = disposition
        self._cursor = cursor
        self._transitioned = False

    def mark_succeeded(self) -> None:
        """Persist successful delivery for a current retryable claim."""
        self._transition("succeeded", None, {"deliver"})

    def mark_failed(self, error_code: str) -> None:
        """Persist a sanitized retryable failure for a current claim."""
        if not error_code or not error_code.strip():
            raise ValueError("error_code must not be empty")
        self._transition("failed", error_code, {"deliver"})

    def mark_skipped(self) -> None:
        """Persist a superseded projection as terminal skipped work."""
        self._transition("skipped", None, {"superseded"})

    def _transition(
        self, state: str, error_code: str | None, allowed: set[str]
    ) -> None:
        if self.disposition not in allowed:
            raise MemoryStoreError("projection claim does not allow this transition")
        if self._transitioned:
            raise MemoryStoreError("projection claim has already transitioned")
        self._cursor.execute(
            "/* memory:claim-mark */ "
            "UPDATE artemis.memory_outbox "
            "SET status = %s, last_error_code = %s, "
            "attempt_count = attempt_count + CASE WHEN %s = 'failed' THEN 1 ELSE 0 END, "
            "delivered_at = CASE WHEN %s = 'succeeded' THEN now() ELSE delivered_at END, "
            "locked_at = NULL, locked_by = NULL "
            "WHERE record_id = %s::uuid AND target = %s "
            "AND status IN ('pending', 'failed')",
            (
                state,
                error_code,
                state,
                state,
                self.revision.record_id,
                self.target,
            ),
        )
        self._transitioned = True


class SqlMemoryStore(Protocol):
    """Transport-neutral canonical memory storage interface."""

    def stage_write(
        self,
        *,
        relative_path: str,
        content: str,
        metadata: Mapping[str, object] | None,
        idempotency_key: str,
        provenance_id: str | None = None,
        source_agent: str | None = None,
    ) -> MemoryWriteReceipt:
        """Commit a revision, current head, and projection event."""

    def mark_delivered(self, event_id: str) -> None:
        """Mark one projection event delivered."""

    def mark_projection_failed(self, event_id: str, error_code: str) -> None:
        """Return a projection event to pending with its failure code."""

    def get_current(self, relative_path: str) -> MemoryRevision | None:
        """Return the current committed revision for a path."""

    def list_current(
        self, relative_path_prefix: str, limit: int | None = None
    ) -> list[MemoryRevision]:
        """Return committed heads beneath one vault-relative folder prefix."""

    def list_pending(self, limit: int = 100) -> list[MemoryWriteReceipt]:
        """Return pending projection work in revision order."""

    def projection_guard(
        self, relative_path: str
    ) -> AbstractContextManager[MemoryRevision | None]:
        """Hold the cross-process path fence and return the current revision."""


class PostgresMemoryStore:
    """Canonical memory store using a short PostgreSQL transaction per operation."""

    _RECORD_COLUMNS = (
        "record_id, memory_id, relative_path, revision, idempotency_key, content, "
        "content_sha256, metadata, provenance_id, source_agent, created_at"
    )
    _CANONICAL_RECORD_COLUMNS = (
        "record_id, memory_id, relative_path, revision, idempotency_key, content, "
        "content_sha256, metadata, provenance_id, source_agent, created_at, namespace, "
        "memory_key, principal_id, parent_provenance_id, requested_projections"
    )

    def __init__(
        self,
        connection_factory: Callable[[], ConnectionLike],
        *,
        close_connections: bool = False,
        enable_legacy_canonical_adapter: bool = False,
    ) -> None:
        """Initialize the store with a factory for PostgreSQL connections.

        Args:
            connection_factory: Callable that returns a psycopg2-compatible connection.
            close_connections: Whether this store owns and closes connections returned
                by the factory after each transaction.
            enable_legacy_canonical_adapter: Explicitly adapt ``stage_write`` to the
                enhanced schema. Disabled for the stable v0001 runtime contract.
        """
        self._connection_factory = connection_factory
        self._close_connections = close_connections
        self._enable_legacy_canonical_adapter = enable_legacy_canonical_adapter

    def stage_canonical_write(
        self,
        *,
        namespace: str,
        key: str,
        relative_path: str,
        content: str,
        metadata: Mapping[str, object],
        idempotency_key: str,
        principal_id: str | None,
        parent_provenance_id: str | None,
        requested_projections: Sequence[str],
        source_agent: str | None = None,
    ) -> CanonicalMemoryWrite:
        """Commit one enhanced record, head, completion, and all outbox events."""
        self._validate_canonical_write(
            namespace,
            key,
            relative_path,
            content,
            idempotency_key,
            principal_id,
            parent_provenance_id,
            requested_projections,
        )
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        encoded_metadata = self._encode_strict_json(metadata, "metadata")
        projections = tuple(requested_projections)

        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    existing = self._find_canonical_idempotency(
                        cursor, namespace, idempotency_key
                    )
                    if existing is not None:
                        return self._canonical_replay(
                            cursor,
                            existing,
                            key,
                            relative_path,
                            content_sha256,
                            projections,
                        )

                    self._lock(cursor, f"idempotency:{namespace}:{idempotency_key}")
                    self._lock(cursor, f"path:{relative_path}")
                    self._lock(cursor, f"logical:{namespace}:{key}")
                    existing = self._find_canonical_idempotency(
                        cursor, namespace, idempotency_key
                    )
                    if existing is not None:
                        return self._canonical_replay(
                            cursor,
                            existing,
                            key,
                            relative_path,
                            content_sha256,
                            projections,
                        )

                    cursor.execute(
                        "/* memory:path-head */ "
                        "SELECT relative_path, memory_id, current_record_id, "
                        "current_revision, namespace, memory_key "
                        "FROM artemis.memory_heads "
                        "WHERE relative_path = %s OR (namespace = %s AND memory_key = %s) "
                        "FOR UPDATE",
                        (relative_path, namespace, key),
                    )
                    head = cursor.fetchone()
                    if head is not None:
                        self._validate_head_binding(head, namespace, key, relative_path)

                    memory_id = (
                        str(self._value(head, "memory_id", 1))
                        if head is not None
                        else str(uuid.uuid4())
                    )
                    next_revision = (
                        int(self._value(head, "current_revision", 3)) + 1
                        if head is not None
                        else 1
                    )
                    record_id = str(uuid.uuid4())
                    completion_id = str(uuid.uuid4())
                    requested_json = json.dumps(list(projections), allow_nan=False)
                    cursor.execute(
                        "/* memory:record-insert */ "
                        "INSERT INTO artemis.memory_records ("
                        "record_id, memory_id, relative_path, revision, idempotency_key, "
                        "content, content_sha256, metadata, provenance_id, source_agent, "
                        "namespace, memory_key, principal_id, parent_provenance_id, "
                        "requested_projections) VALUES ("
                        "%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, "
                        "%s::uuid, %s, %s, %s, %s, %s, %s::jsonb) RETURNING created_at",
                        (
                            record_id,
                            memory_id,
                            relative_path,
                            next_revision,
                            idempotency_key,
                            content,
                            content_sha256,
                            encoded_metadata,
                            completion_id,
                            source_agent,
                            namespace,
                            key,
                            principal_id,
                            parent_provenance_id,
                            requested_json,
                        ),
                    )
                    created_at = self._value(cursor.fetchone(), "created_at", 0)
                    if not isinstance(created_at, datetime):
                        raise MemoryStoreError(
                            "PostgreSQL did not return a revision timestamp"
                        )
                    head_marker = "head-update" if head is not None else "head-insert"
                    if head is None:
                        head_sql = (
                            "INSERT INTO artemis.memory_heads (relative_path, memory_id, "
                            "current_record_id, current_revision, namespace, memory_key) "
                            "VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s)"
                        )
                    else:
                        head_sql = (
                            "WITH next_head(relative_path, memory_id, record_id, revision, "
                            "namespace, memory_key) AS (VALUES "
                            "(%s, %s::uuid, %s::uuid, %s, %s, %s)) "
                            "UPDATE artemis.memory_heads AS h SET memory_id = n.memory_id, "
                            "current_record_id = n.record_id, current_revision = n.revision, "
                            "namespace = n.namespace, memory_key = n.memory_key, updated_at = now() "
                            "FROM next_head AS n WHERE h.relative_path = n.relative_path"
                        )
                    cursor.execute(
                        f"/* memory:{head_marker} */ {head_sql}",
                        (
                            relative_path,
                            memory_id,
                            record_id,
                            next_revision,
                            namespace,
                            key,
                        ),
                    )
                    cursor.execute(
                        "/* memory:provenance-insert */ "
                        "INSERT INTO artemis.memory_completion_provenance ("
                        "record_id, provenance_id, parent_provenance_id, principal_id, "
                        "event_type) VALUES (%s::uuid, %s::uuid, %s, %s, 'memory.write')",
                        (record_id, completion_id, parent_provenance_id, principal_id),
                    )
                    event_ids: dict[str, str] = {}
                    for target in projections:
                        event_id = str(uuid.uuid4())
                        event_ids[target] = event_id
                        cursor.execute(
                            "/* memory:outbox-insert */ "
                            "INSERT INTO artemis.memory_outbox ("
                            "event_id, record_id, memory_id, relative_path, revision, "
                            "target, operation, status) VALUES ("
                            "%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, 'write', 'pending')",
                            (
                                event_id,
                                record_id,
                                memory_id,
                                relative_path,
                                next_revision,
                                target,
                            ),
                        )
        except (CanonicalIdempotencyConflict, CanonicalNamespaceConflict):
            raise
        except MemoryStoreError:
            raise
        except Exception:
            raise MemoryStoreError("failed to stage canonical memory write") from None

        revision = CanonicalMemoryRevision(
            record_id=record_id,
            memory_id=memory_id,
            namespace=namespace,
            key=key,
            relative_path=relative_path,
            revision=next_revision,
            content=content,
            content_sha256=content_sha256,
            metadata=json.loads(encoded_metadata),
            idempotency_key=idempotency_key,
            principal_id=principal_id,
            parent_provenance_id=parent_provenance_id,
            completion_provenance_id=completion_id,
            requested_projections=projections,
            created_at=created_at,
        )
        return CanonicalMemoryWrite(
            revision=revision,
            replayed=False,
            projection_statuses={target: "pending" for target in projections},
            projection_event_ids=event_ids,
        )

    @contextmanager
    def claim_canonical_projection(
        self, record_id: str, target: str
    ) -> Iterator[CanonicalProjectionClaim]:
        """Hold one logical-key transaction lock while a projection is classified."""
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"/* memory:record-by-id */ SELECT {self._CANONICAL_RECORD_COLUMNS} "
                        "FROM artemis.memory_records WHERE record_id = %s::uuid",
                        (record_id,),
                    )
                    record_row = cursor.fetchone()
                    if record_row is None:
                        raise MemoryStoreError("memory record does not exist")
                    revision = self._canonical_revision_from_row(record_row)
                    self._lock(cursor, f"logical:{revision.namespace}:{revision.key}")
                    cursor.execute(
                        f"/* memory:claim-state */ SELECT r."
                        f"{self._CANONICAL_RECORD_COLUMNS.replace(', ', ', r.')}, "
                        "o.target, o.status, "
                        "h.current_record_id FROM artemis.memory_records AS r "
                        "JOIN artemis.memory_outbox AS o ON o.record_id = r.record_id "
                        "JOIN artemis.memory_heads AS h ON h.namespace = r.namespace "
                        "AND h.memory_key = r.memory_key "
                        "WHERE r.record_id = %s::uuid AND o.target = %s FOR UPDATE OF o, h",
                        (record_id, target),
                    )
                    claim_row = cursor.fetchone()
                    if claim_row is None:
                        raise MemoryStoreError("projection event does not exist")
                    state = str(self._value(claim_row, "status", 17))
                    current_id = str(self._value(claim_row, "current_record_id", 18))
                    if state in {"succeeded", "skipped"}:
                        disposition = "terminal"
                    elif current_id != record_id:
                        disposition = "superseded"
                    elif state in {"pending", "failed"}:
                        disposition = "deliver"
                    else:
                        raise MemoryStoreError("projection event has an invalid state")
                    yield CanonicalProjectionClaim(
                        cursor, revision, target, disposition
                    )
        except MemoryStoreError:
            raise
        except Exception:
            raise MemoryStoreError("failed to claim canonical projection") from None

    def read_canonical(
        self, namespace: str, key: str
    ) -> CanonicalMemoryRevision | None:
        """Read the current exact logical memory in one namespace."""
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"/* memory:read */ SELECT r."
                        f"{self._CANONICAL_RECORD_COLUMNS.replace(', ', ', r.')} "
                        "FROM artemis.memory_heads AS h "
                        "JOIN artemis.memory_records AS r "
                        "ON r.record_id = h.current_record_id "
                        "WHERE h.namespace = %s AND h.memory_key = %s",
                        (namespace, key),
                    )
                    row = cursor.fetchone()
        except Exception:
            raise MemoryStoreError("failed to read canonical memory") from None
        return self._canonical_revision_from_row(row) if row is not None else None

    def search_canonical(
        self, namespace: str, query: str, limit: int
    ) -> list[CanonicalMemoryRevision]:
        """Search current record text within exactly one namespace."""
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"/* memory:search */ SELECT r."
                        f"{self._CANONICAL_RECORD_COLUMNS.replace(', ', ', r.')} "
                        "FROM artemis.memory_heads AS h "
                        "JOIN artemis.memory_records AS r "
                        "ON r.record_id = h.current_record_id "
                        "WHERE h.namespace = %s AND r.content ILIKE ('%%' || %s || '%%') "
                        "ORDER BY r.created_at DESC LIMIT %s",
                        (namespace, query, limit),
                    )
                    rows = cursor.fetchall()
        except Exception:
            raise MemoryStoreError("failed to search canonical memory") from None
        return [self._canonical_revision_from_row(row) for row in rows]

    def canonical_projection_status(
        self, namespace: str, record_id: str
    ) -> dict[str, str] | None:
        """Read projection states for one immutable record in one namespace."""
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    cursor.execute(
                        "/* memory:status */ SELECT r.record_id, o.target, o.status "
                        "FROM artemis.memory_records AS r "
                        "LEFT JOIN artemis.memory_outbox AS o ON o.record_id = r.record_id "
                        "WHERE r.namespace = %s AND r.record_id = %s::uuid "
                        "ORDER BY o.target",
                        (namespace, record_id),
                    )
                    rows = cursor.fetchall()
        except Exception:
            raise MemoryStoreError("failed to read projection status") from None
        if not rows:
            return None
        states: dict[str, str] = {}
        for row in rows:
            target = self._value(row, "target", 1)
            if target is None:
                continue
            states[str(target)] = str(self._value(row, "status", 2))
        return states

    def _has_canonical_contract(self) -> bool:
        """Detect whether migration 0002's enhanced record columns are present."""
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    cursor.execute(
                        "/* memory:contract-version */ SELECT EXISTS ("
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = 'artemis' "
                        "AND table_name = 'memory_records' "
                        "AND column_name = 'requested_projections'"
                        ") AS canonical_contract"
                    )
                    row = cursor.fetchone()
        except Exception:
            raise MemoryStoreError("failed to inspect memory store contract") from None
        return bool(self._value(row, "canonical_contract", 0))

    def _stage_legacy_write_after_0002(
        self,
        *,
        relative_path: str,
        content: str,
        metadata: Mapping[str, object] | None,
        idempotency_key: str,
        provenance_id: str | None,
        source_agent: str | None,
    ) -> MemoryWriteReceipt:
        """Map the legacy API to the enhanced transaction after migration 0002."""
        try:
            stored = self.stage_canonical_write(
                namespace="legacy",
                key=relative_path,
                relative_path=relative_path,
                content=content,
                metadata=metadata or {},
                idempotency_key=idempotency_key,
                principal_id=None,
                parent_provenance_id=provenance_id,
                requested_projections=("obsidian",),
                source_agent=source_agent,
            )
        except CanonicalIdempotencyConflict:
            raise IdempotencyConflictError(
                "idempotency key is already bound to another write"
            ) from None
        event_id = stored.projection_event_ids.get("obsidian")
        if event_id is None:
            raise MemoryStoreError(
                "committed memory revision has no Obsidian outbox event"
            )
        revision = stored.revision
        return MemoryWriteReceipt(
            revision=MemoryRevision(
                record_id=revision.record_id,
                memory_id=revision.memory_id,
                relative_path=revision.relative_path,
                revision=revision.revision,
                idempotency_key=revision.idempotency_key,
                content=revision.content,
                content_sha256=revision.content_sha256,
                metadata=revision.metadata,
                provenance_id=revision.completion_provenance_id,
                source_agent=source_agent,
                created_at=revision.created_at,
            ),
            event_id=event_id,
            projection_status=self._legacy_projection_status(
                stored.projection_statuses["obsidian"]
            ),
            duplicate=stored.replayed,
        )

    @staticmethod
    def _legacy_projection_status(status: str) -> str:
        """Preserve the legacy pending/delivered receipt vocabulary over 0002."""
        if status == "failed":
            return "pending"
        if status == "succeeded":
            return "delivered"
        return status

    @staticmethod
    def _lock(cursor: CursorLike, token: str) -> None:
        cursor.execute(
            "/* memory:lock */ "
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (token,),
        )

    @classmethod
    def _lock_path(cls, cursor: CursorLike, relative_path: str) -> None:
        """Acquire every supported path-lock token in one fixed order."""
        cls._lock(cursor, relative_path)
        cls._lock(cursor, f"path:{relative_path}")

    def _find_canonical_idempotency(
        self, cursor: CursorLike, namespace: str, idempotency_key: str
    ) -> CanonicalMemoryRevision | None:
        cursor.execute(
            f"/* memory:idempotency */ SELECT {self._CANONICAL_RECORD_COLUMNS} "
            "FROM artemis.memory_records "
            "WHERE namespace = %s AND idempotency_key = %s",
            (namespace, idempotency_key),
        )
        row = cursor.fetchone()
        return self._canonical_revision_from_row(row) if row is not None else None

    def _canonical_replay(
        self,
        cursor: CursorLike,
        revision: CanonicalMemoryRevision,
        key: str,
        relative_path: str,
        content_sha256: str,
        projections: tuple[str, ...],
    ) -> CanonicalMemoryWrite:
        if (
            revision.key != key
            or revision.relative_path != relative_path
            or revision.content_sha256 != content_sha256
            or set(revision.requested_projections) != set(projections)
        ):
            raise CanonicalIdempotencyConflict(
                "namespace idempotency key is already bound to another write"
            )
        cursor.execute(
            "/* memory:completion */ SELECT provenance_id, parent_provenance_id, "
            "principal_id FROM artemis.memory_completion_provenance "
            "WHERE record_id = %s::uuid",
            (revision.record_id,),
        )
        completion = cursor.fetchone()
        if (
            completion is None
            or revision.completion_provenance_id is None
            or str(self._value(completion, "provenance_id", 0))
            != revision.completion_provenance_id
            or self._nullable_text(self._value(completion, "parent_provenance_id", 1))
            != revision.parent_provenance_id
            or self._nullable_text(self._value(completion, "principal_id", 2))
            != revision.principal_id
        ):
            raise MemoryStoreError(
                "canonical completion provenance is absent or inconsistent"
            )
        statuses, event_ids = self._canonical_events(cursor, revision.record_id)
        expected_targets = set(projections)
        if (
            set(statuses) != expected_targets
            or set(event_ids) != expected_targets
            or any(not event_id for event_id in event_ids.values())
            or any(
                status not in {"pending", "succeeded", "failed", "skipped"}
                for status in statuses.values()
            )
        ):
            raise MemoryStoreError(
                "canonical projection evidence does not match requested projections"
            )
        return CanonicalMemoryWrite(
            revision=revision,
            replayed=True,
            projection_statuses=statuses,
            projection_event_ids=event_ids,
        )

    @staticmethod
    def _canonical_events(
        cursor: CursorLike, record_id: str
    ) -> tuple[dict[str, str], dict[str, str]]:
        cursor.execute(
            "/* memory:events */ SELECT target, status, event_id "
            "FROM artemis.memory_outbox WHERE record_id = %s::uuid ORDER BY target",
            (record_id,),
        )
        statuses: dict[str, str] = {}
        event_ids: dict[str, str] = {}
        for row in cursor.fetchall():
            target = str(PostgresMemoryStore._value(row, "target", 0))
            statuses[target] = str(PostgresMemoryStore._value(row, "status", 1))
            event_ids[target] = str(PostgresMemoryStore._value(row, "event_id", 2))
        return statuses, event_ids

    @staticmethod
    def _nullable_text(value: object) -> str | None:
        """Normalize a nullable database scalar without fabricating evidence."""
        return str(value) if value is not None else None

    @classmethod
    def _canonical_revision_from_row(
        cls, row: Mapping[str, object] | Sequence[object]
    ) -> CanonicalMemoryRevision:
        metadata = cls._value(row, "metadata", 7)
        requested = cls._value(row, "requested_projections", 15)
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if isinstance(requested, str):
            requested = json.loads(requested)
        created_at = cls._value(row, "created_at", 10)
        if (
            not isinstance(metadata, dict)
            or not isinstance(requested, (list, tuple))
            or not all(isinstance(item, str) for item in requested)
            or not isinstance(created_at, datetime)
        ):
            raise MemoryStoreError("PostgreSQL returned an invalid canonical revision")
        return CanonicalMemoryRevision(
            record_id=str(cls._value(row, "record_id", 0)),
            memory_id=str(cls._value(row, "memory_id", 1)),
            relative_path=str(cls._value(row, "relative_path", 2)),
            revision=int(cls._value(row, "revision", 3)),
            idempotency_key=str(cls._value(row, "idempotency_key", 4)),
            content=str(cls._value(row, "content", 5)),
            content_sha256=str(cls._value(row, "content_sha256", 6)),
            metadata=metadata,
            completion_provenance_id=(
                str(value)
                if (value := cls._value(row, "provenance_id", 8)) is not None
                else None
            ),
            created_at=created_at,
            namespace=str(cls._value(row, "namespace", 11)),
            key=str(cls._value(row, "memory_key", 12)),
            principal_id=(
                str(value)
                if (value := cls._value(row, "principal_id", 13)) is not None
                else None
            ),
            parent_provenance_id=(
                str(value)
                if (value := cls._value(row, "parent_provenance_id", 14)) is not None
                else None
            ),
            requested_projections=tuple(requested),
        )

    @staticmethod
    def _validate_head_binding(
        head: Mapping[str, object] | Sequence[object],
        namespace: str,
        key: str,
        relative_path: str,
    ) -> None:
        if (
            str(PostgresMemoryStore._value(head, "namespace", 4)) != namespace
            or str(PostgresMemoryStore._value(head, "memory_key", 5)) != key
            or str(PostgresMemoryStore._value(head, "relative_path", 0))
            != relative_path
        ):
            raise CanonicalNamespaceConflict(
                "relative path or logical key is already bound to another memory"
            )

    @classmethod
    def _validate_canonical_write(
        cls,
        namespace: str,
        key: str,
        relative_path: str,
        content: str,
        idempotency_key: str,
        principal_id: str | None,
        parent_provenance_id: str | None,
        requested_projections: Sequence[str],
    ) -> None:
        cls._validate_relative_path(relative_path)
        for value, name in (
            (namespace, "namespace"),
            (key, "key"),
            (idempotency_key, "idempotency_key"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        for value, name in (
            (principal_id, "principal_id"),
            (parent_provenance_id, "parent_provenance_id"),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must not be empty when provided")
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        projections = tuple(requested_projections)
        if any(target not in {"obsidian", "vector"} for target in projections):
            raise ValueError("requested projections must be obsidian or vector")
        if len(set(projections)) != len(projections):
            raise ValueError("requested projections must be unique")

    @staticmethod
    def _encode_strict_json(metadata: Mapping[str, object], field_name: str) -> str:
        if not isinstance(metadata, Mapping):
            raise TypeError(f"{field_name} must be a mapping")
        try:
            return json.dumps(dict(metadata), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must contain strict JSON values") from exc

    def stage_write(
        self,
        *,
        relative_path: str,
        content: str,
        metadata: Mapping[str, object] | None,
        idempotency_key: str,
        provenance_id: str | None = None,
        source_agent: str | None = None,
    ) -> MemoryWriteReceipt:
        """Commit one immutable revision, its path head, and an outbox event.

        Args:
            relative_path: Validated vault-relative note path.
            content: Complete note content to persist.
            metadata: Optional JSON-compatible metadata associated with the revision.
            idempotency_key: Stable caller-supplied key for retry-safe writes.
            provenance_id: Optional provenance UUID associated with the write.
            source_agent: Optional agent name that originated the write.

        Returns:
            The committed revision and pending projection event, or its duplicate receipt.

        Raises:
            IdempotencyConflictError: If the key belongs to another content or path.
            MemoryStoreError: If PostgreSQL rejects the operation.
        """
        self._validate_write(relative_path, content, idempotency_key)
        if provenance_id is not None:
            if not isinstance(provenance_id, str):
                raise ValueError("provenance_id must be a UUID string")
            try:
                uuid.UUID(provenance_id)
            except ValueError as exc:
                raise ValueError("provenance_id must be a valid UUID") from exc
        if source_agent is not None and (
            not isinstance(source_agent, str) or not source_agent.strip()
        ):
            raise ValueError("source_agent must be a nonempty string")
        encoded_metadata = self._encode_strict_json(metadata or {}, "metadata")
        normalized_metadata = dict(json.loads(encoded_metadata))
        if self._enable_legacy_canonical_adapter and self._has_canonical_contract():
            return self._stage_legacy_write_after_0002(
                relative_path=relative_path,
                content=content,
                metadata=metadata,
                idempotency_key=idempotency_key,
                provenance_id=provenance_id,
                source_agent=source_agent,
            )
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT {self._RECORD_COLUMNS} "
                        "FROM artemis.memory_records "
                        "WHERE idempotency_key = %s",
                        (idempotency_key,),
                    )
                    existing_row = cursor.fetchone()
                    if existing_row is not None:
                        existing = self._revision_from_row(existing_row)
                        if (
                            existing.relative_path != relative_path
                            or existing.content_sha256 != content_sha256
                        ):
                            raise IdempotencyConflictError(
                                "idempotency key is already bound to another write"
                            )
                        cursor.execute(
                            "SELECT event_id, status FROM artemis.memory_outbox "
                            "WHERE record_id = %s AND target = 'obsidian'",
                            (existing.record_id,),
                        )
                        event_row = cursor.fetchone()
                        if event_row is None:
                            raise MemoryStoreError(
                                "committed memory revision has no Obsidian outbox event"
                            )
                        return MemoryWriteReceipt(
                            revision=existing,
                            event_id=str(self._value(event_row, "event_id", 0)),
                            projection_status=str(self._value(event_row, "status", 1)),
                            duplicate=True,
                        )

                    self._lock_path(cursor, relative_path)
                    cursor.execute(
                        "SELECT memory_id, current_revision "
                        "FROM artemis.memory_heads "
                        "WHERE relative_path = %s FOR UPDATE",
                        (relative_path,),
                    )
                    head = cursor.fetchone()
                    memory_id = (
                        str(self._value(head, "memory_id", 0))
                        if head is not None
                        else str(uuid.uuid4())
                    )
                    next_revision = (
                        int(self._value(head, "current_revision", 1)) + 1
                        if head is not None
                        else 1
                    )
                    record_id = str(uuid.uuid4())
                    event_id = str(uuid.uuid4())
                    cursor.execute(
                        "INSERT INTO artemis.memory_records ("
                        "record_id, memory_id, relative_path, revision, idempotency_key, content, "
                        "content_sha256, metadata, provenance_id, source_agent"
                        ") VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, "
                        "%s::uuid, %s) RETURNING created_at",
                        (
                            record_id,
                            memory_id,
                            relative_path,
                            next_revision,
                            idempotency_key,
                            content,
                            content_sha256,
                            encoded_metadata,
                            provenance_id,
                            source_agent,
                        ),
                    )
                    created_row = cursor.fetchone()
                    created_at = self._value(created_row, "created_at", 0)
                    if not isinstance(created_at, datetime):
                        raise MemoryStoreError(
                            "PostgreSQL did not return a revision timestamp"
                        )

                    if head is None:
                        cursor.execute(
                            "INSERT INTO artemis.memory_heads ("
                            "relative_path, memory_id, current_record_id, current_revision"
                            ") VALUES (%s, %s::uuid, %s::uuid, %s)",
                            (relative_path, memory_id, record_id, next_revision),
                        )
                    else:
                        cursor.execute(
                            "UPDATE artemis.memory_heads "
                            "SET current_record_id = %s::uuid, current_revision = %s, updated_at = now() "
                            "WHERE relative_path = %s",
                            (record_id, next_revision, relative_path),
                        )
                    cursor.execute(
                        "/* memory:supersede-obsolete */ "
                        "UPDATE artemis.memory_outbox "
                        "SET status = 'delivered', "
                        "last_error_code = 'superseded_by_newer_revision', "
                        "delivered_at = now() "
                        "WHERE relative_path = %s AND revision < %s "
                        "AND status IN ('pending', 'processing')",
                        (relative_path, next_revision),
                    )
                    cursor.execute(
                        "INSERT INTO artemis.memory_outbox ("
                        "event_id, record_id, memory_id, relative_path, revision, "
                        "target, operation, status"
                        ") VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, "
                        "'obsidian', 'write', 'pending')",
                        (event_id, record_id, memory_id, relative_path, next_revision),
                    )
        except IdempotencyConflictError:
            raise
        except MemoryStoreError:
            raise
        except Exception as exc:
            if self._is_unique_violation(exc):
                winner = self._find_idempotency_receipt(idempotency_key)
                if winner is not None:
                    if (
                        winner.revision.relative_path != relative_path
                        or winner.revision.content_sha256 != content_sha256
                    ):
                        raise IdempotencyConflictError(
                            "idempotency key is already bound to another write"
                        ) from None
                    return replace(winner, duplicate=True)
            raise MemoryStoreError("failed to stage canonical memory write") from None

        revision = MemoryRevision(
            record_id=record_id,
            memory_id=memory_id,
            relative_path=relative_path,
            revision=next_revision,
            idempotency_key=idempotency_key,
            content=content,
            content_sha256=content_sha256,
            metadata=normalized_metadata,
            provenance_id=provenance_id,
            source_agent=source_agent,
            created_at=created_at,
        )
        return MemoryWriteReceipt(
            revision=revision,
            event_id=event_id,
            projection_status="pending",
            duplicate=False,
        )

    def get_current(self, relative_path: str) -> MemoryRevision | None:
        """Return the committed current revision for one vault-relative path.

        Args:
            relative_path: Vault-relative path whose head should be read.

        Returns:
            The current revision, or ``None`` when the path has no committed head.
        """
        self._validate_relative_path(relative_path)
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    revision = self._get_current_with_cursor(cursor, relative_path)
        except Exception:
            raise MemoryStoreError("failed to read canonical memory revision") from None
        return revision

    def list_current(
        self, relative_path_prefix: str, limit: int | None = None
    ) -> list[MemoryRevision]:
        """Return committed heads below a folder, or all heads for an empty prefix."""
        if relative_path_prefix:
            self._validate_relative_path(relative_path_prefix, require_leaf=False)
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least one")
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    query = (
                        f"SELECT r.{self._RECORD_COLUMNS.replace(', ', ', r.')} "
                        "FROM artemis.memory_heads AS h "
                        "JOIN artemis.memory_records AS r "
                        "ON r.record_id = h.current_record_id "
                    )
                    parameters: tuple[object, ...] = ()
                    if relative_path_prefix:
                        escaped_prefix = (
                            relative_path_prefix.rstrip("/")
                            .replace("\\", "\\\\")
                            .replace("%", "\\%")
                            .replace("_", "\\_")
                        )
                        query += "WHERE h.relative_path LIKE %s ESCAPE E'\\\\' "
                        parameters = (f"{escaped_prefix}/%",)
                    query += "ORDER BY h.relative_path"
                    if limit is not None:
                        query += " LIMIT %s"
                        parameters += (limit,)
                    cursor.execute(query, parameters)
                    rows = cursor.fetchall()
        except Exception:
            raise MemoryStoreError("failed to list canonical memory revisions") from None
        return [self._revision_from_row(row) for row in rows]

    @contextmanager
    def projection_guard(self, relative_path: str) -> Iterator[MemoryRevision | None]:
        """Fence classification and projection against concurrent path writes."""
        self._validate_relative_path(relative_path)
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    self._lock_path(cursor, relative_path)
                    yield self._get_current_with_cursor(cursor, relative_path)
        except MemoryStoreError:
            raise
        except Exception:
            raise MemoryStoreError(
                "failed to guard canonical memory projection"
            ) from None

    def _get_current_with_cursor(
        self, cursor: CursorLike, relative_path: str
    ) -> MemoryRevision | None:
        """Read the current head using an existing transaction cursor."""
        cursor.execute(
            f"SELECT r.{self._RECORD_COLUMNS.replace(', ', ', r.')} "
            "FROM artemis.memory_heads AS h "
            "JOIN artemis.memory_records AS r "
            "ON r.record_id = h.current_record_id "
            "WHERE h.relative_path = %s",
            (relative_path,),
        )
        row = cursor.fetchone()
        return self._revision_from_row(row) if row is not None else None

    def mark_delivered(self, event_id: str) -> None:
        """Mark an Obsidian projection event delivered after acknowledgement.

        Args:
            event_id: Identifier of the acknowledged outbox event.
        """
        self._validate_event_id(event_id)
        self._update_outbox(
            "/* memory:legacy-delivered */ UPDATE artemis.memory_outbox "
            "SET status = CASE WHEN EXISTS ("
            "SELECT 1 FROM pg_constraint "
            "WHERE conrelid = 'artemis.memory_outbox'::regclass "
            "AND conname = 'memory_outbox_status_check' "
            "AND pg_get_constraintdef(oid) LIKE '%%succeeded%%'"
            ") THEN 'succeeded' ELSE 'delivered' END, "
            "delivered_at = now(), locked_at = NULL, locked_by = NULL "
            "WHERE event_id = %s::uuid",
            (event_id,),
            "failed to mark projection delivered",
        )

    def mark_projection_failed(self, event_id: str, error_code: str) -> None:
        """Record a projection failure and return the event to pending work.

        Args:
            event_id: Identifier of the failed outbox event.
            error_code: Stable non-secret error code for retry diagnostics.
        """
        self._validate_event_id(event_id)
        if not error_code:
            raise ValueError("error_code must not be empty")
        self._update_outbox(
            "/* memory:legacy-failed */ UPDATE artemis.memory_outbox "
            "SET status = CASE "
            "WHEN status NOT IN ('pending', 'processing', 'failed') THEN status "
            "WHEN EXISTS ("
            "SELECT 1 FROM pg_constraint "
            "WHERE conrelid = 'artemis.memory_outbox'::regclass "
            "AND conname = 'memory_outbox_status_check' "
            "AND pg_get_constraintdef(oid) LIKE '%%failed%%'"
            ") THEN 'failed' ELSE 'pending' END, "
            "attempt_count = CASE "
            "WHEN status IN ('pending', 'processing', 'failed') "
            "THEN attempt_count + 1 ELSE attempt_count END, "
            "last_error_code = CASE "
            "WHEN status IN ('pending', 'processing', 'failed') "
            "THEN %s ELSE last_error_code END, "
            "locked_at = CASE "
            "WHEN status IN ('pending', 'processing', 'failed') "
            "THEN NULL ELSE locked_at END, "
            "locked_by = CASE "
            "WHEN status IN ('pending', 'processing', 'failed') "
            "THEN NULL ELSE locked_by END "
            "WHERE event_id = %s::uuid",
            (error_code, event_id),
            "failed to record projection failure",
        )

    def list_pending(self, limit: int = 100) -> list[MemoryWriteReceipt]:
        """List pending Obsidian projection events in revision order.

        Args:
            limit: Maximum number of pending events to return.

        Returns:
            Pending write receipts, ordered by their next eligible attempt.
        """
        if limit < 1:
            raise ValueError("limit must be at least one")
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT r.{self._RECORD_COLUMNS.replace(', ', ', r.')}, "
                        "o.event_id, o.status "
                        "FROM artemis.memory_outbox AS o "
                        "JOIN artemis.memory_records AS r ON r.record_id = o.record_id "
                        "WHERE o.status IN ('pending', 'failed') "
                        "ORDER BY o.next_attempt_at, o.revision "
                        "LIMIT %s",
                        (limit,),
                    )
                    rows = cursor.fetchall()
        except Exception:
            raise MemoryStoreError("failed to list pending projection events") from None
        return [
            MemoryWriteReceipt(
                revision=self._revision_from_row(row),
                event_id=str(self._value(row, "event_id", 11)),
                projection_status=self._legacy_projection_status(
                    str(self._value(row, "status", 12))
                ),
                duplicate=False,
            )
            for row in rows
        ]

    def _update_outbox(
        self, query: str, parameters: Sequence[object], message: str
    ) -> None:
        """Execute one bounded transactional outbox state transition."""
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    cursor.execute(query, parameters)
                    if cursor.rowcount != 1:
                        raise MemoryStoreError("projection event does not exist")
        except MemoryStoreError:
            raise
        except Exception:
            raise MemoryStoreError(message) from None

    def _find_idempotency_receipt(
        self, idempotency_key: str
    ) -> MemoryWriteReceipt | None:
        """Read a winning idempotent write after a unique-constraint race."""
        try:
            with self._transaction_connection() as connection:  # noqa: SIM117
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"SELECT {self._RECORD_COLUMNS} "
                        "FROM artemis.memory_records "
                        "WHERE idempotency_key = %s",
                        (idempotency_key,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    revision = self._revision_from_row(row)
                    cursor.execute(
                        "SELECT event_id, status FROM artemis.memory_outbox "
                        "WHERE record_id = %s AND target = 'obsidian'",
                        (revision.record_id,),
                    )
                    event_row = cursor.fetchone()
        except Exception:
            raise MemoryStoreError(
                "failed to re-read idempotent memory write"
            ) from None
        if event_row is None:
            raise MemoryStoreError(
                "committed memory revision has no Obsidian outbox event"
            )
        return MemoryWriteReceipt(
            revision=revision,
            event_id=str(self._value(event_row, "event_id", 0)),
            projection_status=str(self._value(event_row, "status", 1)),
            duplicate=True,
        )

    @contextmanager
    def _transaction_connection(self) -> Iterator[ConnectionLike]:
        """Yield one transaction connection and close it when this store owns it."""
        connection = self._connection_factory()
        try:
            with connection:
                yield connection
        finally:
            if self._close_connections:
                connection.close()

    @staticmethod
    def _is_unique_violation(error: Exception) -> bool:
        """Return whether a driver exception represents PostgreSQL SQLSTATE 23505."""
        return (
            getattr(error, "pgcode", None) == "23505"
            or getattr(error, "sqlstate", None) == "23505"
        )

    @staticmethod
    def _value(
        row: Mapping[str, object] | Sequence[object] | None, key: str, index: int
    ) -> object:
        """Read one column from either a mapping or psycopg tuple row."""
        if row is None:
            raise MemoryStoreError("PostgreSQL returned no required row")
        if isinstance(row, Mapping):
            return row[key]
        return row[index]

    @classmethod
    def _revision_from_row(
        cls, row: Mapping[str, object] | Sequence[object]
    ) -> MemoryRevision:
        """Convert an explicit memory-record SQL row into a typed revision."""
        metadata = cls._value(row, "metadata", 7)
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        created_at = cls._value(row, "created_at", 10)
        if not isinstance(metadata, dict) or not isinstance(created_at, datetime):
            raise MemoryStoreError("PostgreSQL returned an invalid memory revision")
        return MemoryRevision(
            record_id=str(cls._value(row, "record_id", 0)),
            memory_id=str(cls._value(row, "memory_id", 1)),
            relative_path=str(cls._value(row, "relative_path", 2)),
            revision=int(cls._value(row, "revision", 3)),
            idempotency_key=str(cls._value(row, "idempotency_key", 4)),
            content=str(cls._value(row, "content", 5)),
            content_sha256=str(cls._value(row, "content_sha256", 6)),
            metadata=metadata,
            provenance_id=(
                str(provenance_id)
                if (provenance_id := cls._value(row, "provenance_id", 8)) is not None
                else None
            ),
            source_agent=(
                str(source_agent)
                if (source_agent := cls._value(row, "source_agent", 9)) is not None
                else None
            ),
            created_at=created_at,
        )

    @staticmethod
    def _validate_write(relative_path: str, content: str, idempotency_key: str) -> None:
        """Validate values whose invalid form must not reach PostgreSQL."""
        PostgresMemoryStore._validate_relative_path(relative_path)
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")

    @staticmethod
    def _validate_relative_path(
        relative_path: str, *, require_leaf: bool = True
    ) -> None:
        """Reject non-relative and parent-traversal vault paths."""
        if not isinstance(relative_path, str) or not relative_path:
            raise ValueError("relative_path must not be empty")
        normalized = relative_path.replace("\\", "/")
        segments = normalized.split("/")
        is_windows_absolute = (
            len(relative_path) > 2
            and relative_path[0].isalpha()
            and relative_path[1] == ":"
            and relative_path[2] in "/\\"
        )
        if (
            relative_path.startswith(("/", "\\"))
            or os.path.isabs(relative_path)
            or PurePath(relative_path).is_absolute()
            or is_windows_absolute
            or any(segment == ".." for segment in normalized.split("/"))
        ):
            raise ValueError(
                "relative_path must be vault-relative without parent traversal"
            )
        if "\\" in relative_path or any(segment in {"", "."} for segment in segments):
            raise ValueError("relative_path must use one canonical POSIX form")
        if relative_path != unicodedata.normalize("NFC", relative_path):
            raise ValueError("relative_path must use canonical NFC Unicode")
        if require_leaf:
            leaf_stem, separator, leaf_suffix = segments[-1].rpartition(".")
            if not separator or not leaf_stem or not leaf_suffix:
                raise ValueError("relative_path must identify a file leaf with a suffix")
            if any("." in segment.lstrip(".") for segment in segments[:-1]):
                raise ValueError(
                    "relative_path file leaf cannot be an ancestor directory"
                )

    @staticmethod
    def _validate_event_id(event_id: str) -> None:
        """Reject blank event identifiers before issuing an update."""
        if not event_id:
            raise ValueError("event_id must not be empty")
