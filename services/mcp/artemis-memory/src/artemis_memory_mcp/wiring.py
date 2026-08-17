"""Dependency wiring for the artemis-memory MCP server.

Builds the canonical ``MemoryService`` from operator-supplied environment
configuration. Nothing here opens a database connection or runs a migration
at import time; ``build_memory_service()`` only constructs lazy factories and
adapters, and the underlying store opens a connection per operation.
"""

from __future__ import annotations

import os

from src.integration.sql_memory_store import ConnectionLike, PostgresMemoryStore
from src.mcp.vector_store import create_vector_store
from src.memory.backends.obsidian import ObsidianMemoryProjection
from src.memory.backends.postgres import PostgresMemoryLedger
from src.memory.backends.vector import VectorMemoryProjection
from src.memory.service import MemoryService
from src.obsidian_integration.manager import ObsidianManager


class MemoryServerConfigurationError(RuntimeError):
    """Raised when required deployment configuration is missing or invalid."""


def _positive_integer_setting(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise MemoryServerConfigurationError(
            f"{name} must be a positive integer"
        ) from exc
    if value < 1:
        raise MemoryServerConfigurationError(f"{name} must be a positive integer")
    return value


def _build_connection_factory():
    database_url = os.getenv("ARTEMIS_MEMORY_DATABASE_URL", "").strip()
    if not database_url:
        raise MemoryServerConfigurationError(
            "ARTEMIS_MEMORY_DATABASE_URL is required to serve artemis-memory"
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

    return connection_factory


def _build_vector_store():
    """Build the configured vector projection, failing closed on an explicit choice.

    An operator who did not set ``ARTEMIS_VECTOR_BACKEND`` gets the always-available
    local SQLite store. An operator who explicitly selected ``supabase`` gets a real
    failure if it cannot be constructed, rather than a silent SQLite substitution
    that would make the projection look durable without matching the operator's
    intent.
    """
    backend = os.getenv("ARTEMIS_VECTOR_BACKEND", "sqlite").strip().lower()
    if backend == "supabase":
        try:
            from src.mcp.supabase_vector_store import SupabaseVectorStore

            return SupabaseVectorStore()
        except Exception as exc:
            raise MemoryServerConfigurationError(
                f"ARTEMIS_VECTOR_BACKEND=supabase was selected but the vector "
                f"store could not be constructed: {exc}"
            ) from exc
    return create_vector_store()


def build_memory_service() -> MemoryService:
    """Build the canonical ``MemoryService`` from environment configuration."""
    ledger = PostgresMemoryLedger(
        PostgresMemoryStore(_build_connection_factory(), close_connections=True)
    )
    projections = [
        ObsidianMemoryProjection(ObsidianManager()),
        VectorMemoryProjection(_build_vector_store()),
    ]
    return MemoryService(ledger, projections)
