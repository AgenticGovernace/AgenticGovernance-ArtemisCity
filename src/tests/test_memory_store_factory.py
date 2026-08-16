"""Runtime selection contracts for canonical SQL memory storage."""

from __future__ import annotations

import pytest


def test_legacy_backend_returns_none(monkeypatch):
    """Legacy selection retains the existing non-SQL memory bus."""
    from src.integration.memory_store_factory import create_sql_memory_store

    monkeypatch.setenv("ARTEMIS_MEMORY_BACKEND", "legacy")
    monkeypatch.delenv("ARTEMIS_MEMORY_DATABASE_URL", raising=False)

    assert create_sql_memory_store() is None


def test_neon_backend_without_url_fails_closed(monkeypatch):
    """An explicit Neon selection cannot silently become a local store."""
    from src.integration.memory_store_factory import (
        MemoryStoreConfigurationError,
        create_sql_memory_store,
    )

    monkeypatch.setenv("ARTEMIS_MEMORY_BACKEND", "neon")
    monkeypatch.delenv("ARTEMIS_MEMORY_DATABASE_URL", raising=False)

    with pytest.raises(MemoryStoreConfigurationError) as error:
        create_sql_memory_store()

    assert error.value.code == "MEMORY_DATABASE_CONFIGURATION_ERROR"
    assert "ARTEMIS_MEMORY_DATABASE_URL" in str(error.value)


def test_neon_connection_failure_never_returns_sqlite(monkeypatch):
    """A broken Neon connection remains a canonical-store failure."""
    from src.integration.memory_store_factory import create_sql_memory_store
    from src.integration.sql_memory_store import MemoryStoreError

    monkeypatch.setenv("ARTEMIS_MEMORY_BACKEND", "neon")
    monkeypatch.setenv("ARTEMIS_MEMORY_DATABASE_URL", "postgresql://secret-host/db")

    def fail_connection(*args, **kwargs):
        raise OSError("connection unavailable")

    monkeypatch.setattr("psycopg2.connect", fail_connection)

    store = create_sql_memory_store()
    with pytest.raises(MemoryStoreError) as error:
        store.get_current("notes/alpha.md")

    assert str(error.value) == "failed to read canonical memory revision"
    assert "postgresql://" not in str(error.value)


def test_postgres_backend_builds_store_with_short_connection_factory(monkeypatch):
    """Postgres configuration defers a timeout-bound connection per operation."""
    from src.integration.memory_store_factory import create_sql_memory_store

    captured: dict[str, object] = {}

    class Connection:
        pass

    def connect(dsn, **kwargs):
        captured["dsn"] = dsn
        captured.update(kwargs)
        return Connection()

    monkeypatch.setenv("ARTEMIS_MEMORY_BACKEND", "postgres")
    monkeypatch.setenv("ARTEMIS_MEMORY_DATABASE_URL", "postgresql://operator-host/db")
    monkeypatch.setenv("ARTEMIS_MEMORY_DB_CONNECT_TIMEOUT_SECONDS", "7")
    monkeypatch.setattr("psycopg2.connect", connect)

    store = create_sql_memory_store()

    assert captured == {}
    connection = store._connection_factory()
    assert isinstance(connection, Connection)
    assert captured == {
        "dsn": "postgresql://operator-host/db",
        "connect_timeout": 7,
        "options": "-c statement_timeout=5000",
    }


@pytest.mark.parametrize("raw_timeout", ["0", "-1", "not-an-integer"])
def test_statement_timeout_must_be_a_positive_integer(monkeypatch, raw_timeout):
    """Invalid statement deadlines fail before a connection can be constructed."""
    from src.integration.memory_store_factory import (
        MemoryStoreConfigurationError,
        create_sql_memory_store,
    )

    monkeypatch.setenv("ARTEMIS_MEMORY_BACKEND", "postgres")
    monkeypatch.setenv("ARTEMIS_MEMORY_DATABASE_URL", "postgresql://operator-host/db")
    monkeypatch.setenv("ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS", raw_timeout)

    with pytest.raises(MemoryStoreConfigurationError) as error:
        create_sql_memory_store()

    assert error.value.code == "MEMORY_DATABASE_CONFIGURATION_ERROR"
    assert str(error.value) == (
        "ARTEMIS_MEMORY_DB_STATEMENT_TIMEOUT_MS must be a positive integer"
    )
