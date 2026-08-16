"""Immutable domain contracts for canonical Artemis City memory writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MemoryError(Exception):
    """Base exception for canonical memory operations."""


class MemoryLedgerUnavailable(MemoryError):
    """Raised when the canonical ledger cannot complete a write."""


class MemoryIdempotencyConflict(MemoryError):
    """Raised when an idempotency key is reused for different input."""


class MemoryNamespaceConflict(MemoryError):
    """Raised when a projection path belongs to another logical memory."""


class MemoryValidationError(MemoryError, ValueError):
    """Raised when a memory command or query violates the domain contract."""


class LedgerState(str, Enum):
    """Durable state of the canonical ledger write."""

    SUCCEEDED = "succeeded"


class ProjectionState(str, Enum):
    """Durable state of one projection outbox event."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class WriteDisposition(str, Enum):
    """Whether a write created a version or replayed an existing one."""

    CREATED = "created"
    REPLAYED = "replayed"


class ClaimDisposition(str, Enum):
    """Ledger classification for a projection delivery claim."""

    DELIVER = "deliver"
    SUPERSEDED = "superseded"
    TERMINAL = "terminal"


def validate_required_text(value: str, field_name: str) -> None:
    """Reject missing or whitespace-only domain identifiers."""
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError(f"{field_name} must be a non-empty string")


def validate_relative_path(value: str, field_name: str) -> None:
    """Validate a vault-relative POSIX path without normalizing its bytes."""
    validate_required_text(value, field_name)
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise MemoryValidationError(f"{field_name} must be a safe relative path")
    if any(part in {"", ".", ".."} or not part.strip() for part in value.split("/")):
        raise MemoryValidationError(f"{field_name} contains an unsafe path component")


def validate_namespace(namespace: str) -> None:
    """Validate a namespace used in a derived memory path."""
    validate_relative_path(namespace, "namespace")


def validate_key(key: str) -> None:
    """Validate a logical key used in a derived memory path."""
    validate_relative_path(key, "key")


@dataclass(frozen=True)
class MemoryWriteCommand:
    """Governed request to create or replay one canonical memory version."""

    namespace: str
    key: str
    content: str
    metadata: dict[str, object]
    idempotency_key: str
    principal_id: str
    parent_provenance_id: str
    requested_projections: tuple[str, ...]
    projection_path: str | None = None

    def __post_init__(self) -> None:
        validate_namespace(self.namespace)
        validate_key(self.key)
        validate_required_text(self.idempotency_key, "idempotency_key")
        validate_required_text(self.principal_id, "principal_id")
        validate_required_text(self.parent_provenance_id, "parent_provenance_id")
        if not isinstance(self.content, str):
            raise MemoryValidationError("content must be a string")
        if not isinstance(self.metadata, dict):
            raise MemoryValidationError("metadata must be a dictionary")

        projections = tuple(self.requested_projections)
        for projection in projections:
            validate_required_text(projection, "projection")
        if len(set(projections)) != len(projections):
            raise MemoryValidationError("requested projections must be unique")
        object.__setattr__(self, "requested_projections", projections)

        path = self.projection_path
        if path is None:
            suffix = "" if self.key.endswith(".md") else ".md"
            path = f"Memory/{self.namespace}/{self.key}{suffix}"
            object.__setattr__(self, "projection_path", path)
        validate_relative_path(path, "projection_path")


@dataclass(frozen=True)
class MemoryRecord:
    """One immutable version of a logical memory."""

    record_id: str
    memory_id: str
    namespace: str
    key: str
    projection_path: str
    version: int
    content: str
    content_sha256: str
    metadata: dict[str, object]
    idempotency_key: str
    principal_id: str | None
    parent_provenance_id: str | None
    completion_provenance_id: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        validate_required_text(self.record_id, "record_id")
        validate_required_text(self.memory_id, "memory_id")
        validate_namespace(self.namespace)
        validate_key(self.key)
        validate_relative_path(self.projection_path, "projection_path")
        if self.version < 1:
            raise MemoryValidationError("version must be at least 1")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise MemoryValidationError("created_at must be timezone-aware")


@dataclass(frozen=True)
class LedgerWrite:
    """Durable ledger result, including outbox-owned state and event IDs."""

    record: MemoryRecord
    disposition: WriteDisposition
    projection_states: dict[str, ProjectionState]
    projection_event_ids: dict[str, str]
    ledger_state: LedgerState = field(default=LedgerState.SUCCEEDED, init=False)


@dataclass(frozen=True)
class MemoryWriteReceipt:
    """Caller-visible result after best-effort projection delivery."""

    record: MemoryRecord
    disposition: WriteDisposition
    ledger_state: LedgerState
    projection_states: dict[str, ProjectionState]
    summary: str
