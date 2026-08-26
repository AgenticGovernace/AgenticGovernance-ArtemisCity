"""Runtime construction for the canonical SQL memory store."""

from __future__ import annotations

import os

from .sql_memory_store import ConnectionLike, PostgresMemoryStore, SqlMemoryStore


class MemoryStoreConfigurationError(RuntimeError):
    """Raised when an explicitly selected SQL memory backend is unusable."""

    code = "MEMORY_DATABASE_CONFIGURATION_ERROR"


def create_sql_memory_store() -> SqlMemoryStore | None:
    """Return the configured canonical SQL store, or ``None`` for legacy mode.

    PostgreSQL and Neon are explicit operator choices.  Invalid selection never
    degrades to a local database because that would make the projection appear
    durable without a canonical commit.
    """
    backend = os.getenv("ARTEMIS_MEMORY_BACKEND", "legacy").strip().lower()
    if backend in {"", "legacy", "disabled"}:
        return None
    if backend not in {"postgres", "neon"}:
        raise MemoryStoreConfigurationError("unsupported ARTEMIS_MEMORY_BACKEND")

    database_url = os.getenv("ARTEMIS_MEMORY_DATABASE_URL", "").strip()
    if not database_url:
        raise MemoryStoreConfigurationError(
            "ARTEMIS_MEMORY_DATABASE_URL is required for SQL memory storage"
        )

    connect_timeout = _positive_integer_setting(
        "ARTEMIS_MEMORY_DB_CONNECT_TIMEOUT_SECONDS", "10"
    )
    statement_timeout_ms = _positive_integer_setting(
        "ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS", "5000"
    )

    def connection_factory() -> ConnectionLike:
        import psycopg2

        return psycopg2.connect(
            database_url,
            connect_timeout=connect_timeout,
            options=f"-c statement_timeout={statement_timeout_ms}",
        )

    return PostgresMemoryStore(connection_factory, close_connections=True)


def _positive_integer_setting(name: str, default: str) -> int:
    """Read one positive integer setting without exposing other configuration."""
    raw_timeout = os.getenv(name, default)
    try:
        timeout = int(raw_timeout)
    except ValueError as exc:
        raise MemoryStoreConfigurationError(
            f"{name} must be a positive integer"
        ) from exc
    if timeout < 1:
        raise MemoryStoreConfigurationError(f"{name} must be a positive integer")
    return timeout
