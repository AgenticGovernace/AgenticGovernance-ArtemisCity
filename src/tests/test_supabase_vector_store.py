"""Tests for the Supabase pgvector backend and the vector-store factory.

The Supabase backend is exercised against a fake psycopg2 connection layer;
no test in this module may open a real network connection (the repository
conftest strips Supabase DSNs for exactly that reason).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import src.mcp.supabase_vector_store as svs
from src.mcp.supabase_vector_store import (
    SupabaseVectorStore,
    _redact_dsn,
    _vector_literal,
)
from src.mcp.vector_store import LocalVectorStore, create_vector_store

FAKE_DSN = "postgresql://postgres:secret@db.example.supabase.co:5432/postgres"


class FakeOperationalError(Exception):
    pass


class FakeCursor:
    def __init__(self, connection):
        self._connection = connection
        self.rowcount = 0
        self._results = []

    def execute(self, sql, params=()):
        self._connection.executed.append((" ".join(sql.split()), tuple(params)))
        self._results = self._connection.next_results
        self._connection.next_results = []
        self.rowcount = self._connection.next_rowcount

    def fetchall(self):
        return list(self._results)

    def fetchone(self):
        return self._results[0] if self._results else None


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.next_results = []
        self.next_rowcount = 0
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self)


@pytest.fixture
def fake_pg(monkeypatch):
    connection = FakeConnection()
    fake_module = SimpleNamespace(
        connect=lambda dsn: connection,
        OperationalError=FakeOperationalError,
    )
    monkeypatch.setattr(svs, "psycopg2", fake_module)
    return connection


@pytest.fixture
def store(fake_pg, monkeypatch):
    monkeypatch.setenv("ARTEMIS_SUPABASE_DB_URL", FAKE_DSN)
    built = SupabaseVectorStore()
    fake_pg.executed.clear()
    return built


def test_vector_store_create_vector_store_defaults_to_sqlite(monkeypatch):
    monkeypatch.delenv("ARTEMIS_VECTOR_BACKEND", raising=False)
    assert isinstance(create_vector_store(), LocalVectorStore)


def test_vector_store_create_vector_store_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("ARTEMIS_VECTOR_BACKEND", "oracle")
    with pytest.raises(ValueError, match="ARTEMIS_VECTOR_BACKEND"):
        create_vector_store()


def test_vector_store_create_vector_store_supabase_without_dsn_falls_back(
    monkeypatch, caplog
):
    monkeypatch.setenv("ARTEMIS_VECTOR_BACKEND", "supabase")
    monkeypatch.delenv("ARTEMIS_SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    built = create_vector_store()
    assert isinstance(built, LocalVectorStore)


def test_vector_store_create_vector_store_supabase_builds_backend(fake_pg, monkeypatch):
    monkeypatch.setenv("ARTEMIS_VECTOR_BACKEND", "supabase")
    monkeypatch.setenv("ARTEMIS_SUPABASE_DB_URL", FAKE_DSN)
    built = create_vector_store()
    assert isinstance(built, SupabaseVectorStore)


def test_supabase_vector_store_init_requires_dsn(fake_pg, monkeypatch):
    monkeypatch.delenv("ARTEMIS_SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    with pytest.raises(ValueError, match="connection string"):
        SupabaseVectorStore()


def test_supabase_vector_store_init_rejects_bad_table(fake_pg):
    with pytest.raises(ValueError, match="table name"):
        SupabaseVectorStore(dsn=FAKE_DSN, table="vectors; DROP TABLE agents")


def test_supabase_vector_store_init_creates_extension_and_table(fake_pg):
    SupabaseVectorStore(dsn=FAKE_DSN)
    statements = [sql for sql, _ in fake_pg.executed]
    assert statements[0] == "CREATE EXTENSION IF NOT EXISTS vector"
    assert "CREATE TABLE IF NOT EXISTS artemis_vectors" in statements[1]
    assert "embedding vector(16) NOT NULL" in statements[1]


def test_supabase_vector_store_upsert_writes_vector_literal(store, fake_pg):
    store.upsert("doc-1", "hello world", {"decay_score": 0.5, "kind": "note"})
    sql, params = fake_pg.executed[0]
    assert "INSERT INTO artemis_vectors" in sql
    assert "ON CONFLICT (doc_id) DO UPDATE" in sql
    assert params[0] == "doc-1"
    assert params[1].startswith("[") and params[1].endswith("]")
    assert json.loads(params[2])["kind"] == "note"
    assert params[4] == 0.5


def test_supabase_vector_store_query_converts_distance_to_similarity(store, fake_pg):
    fake_pg.next_results = [
        ("doc-1", 0.9, {"kind": "note"}, "hello"),
        ("doc-2", 0.1, json.dumps({"kind": "other"}), "bye"),
    ]
    results = store.query("hello", top_k=2)
    sql, params = fake_pg.executed[0]
    assert "1 - (embedding <=> %s::vector)" in sql
    assert "ORDER BY embedding <=> %s::vector" in sql
    assert params[2] == 2
    assert results[0] == ("doc-1", 0.9, {"kind": "note"})
    # JSON-string metadata (older rows) parses the same as native JSONB dicts
    assert results[1][2] == {"kind": "other"}


def test_supabase_vector_store_query_include_content_returns_content(store, fake_pg):
    fake_pg.next_results = [("doc-1", 0.8, {}, "the content")]
    results = store.query("q", top_k=1, include_content=True)
    assert results == [("doc-1", 0.8, {}, "the content")]


def test_supabase_vector_store_fetch_all_round_trips_records(store, fake_pg):
    fake_pg.next_results = [
        (
            "doc-1",
            "[0.5,0.5]",
            {"kind": "note"},
            "hello",
            0.75,
            "2026-07-25T00:00:00+00:00",
            True,
            "2026-07-01T00:00:00+00:00",
        )
    ]
    (record,) = list(store.fetch_all())
    assert record.doc_id == "doc-1"
    assert record.embedding == [0.5, 0.5]
    assert record.weight == 0.75
    assert record.archived is True
    assert record.metadata["decay_score"] == 0.75
    assert record.metadata["archived"] is True


def test_supabase_vector_store_update_decay_state_reports_match(store, fake_pg):
    fake_pg.next_rowcount = 1
    assert store.update_decay_state(
        "doc-1", weight=0.4, last_access="2026-07-25T00:00:00+00:00", archived=True
    )
    sql, params = fake_pg.executed[0]
    assert "UPDATE artemis_vectors SET weight" in sql
    assert params == (0.4, "2026-07-25T00:00:00+00:00", True, "doc-1")

    fake_pg.next_rowcount = 0
    assert not store.update_decay_state(
        "missing", weight=1.0, last_access="x", archived=False
    )


def test_supabase_vector_store_count_returns_int(store, fake_pg):
    fake_pg.next_results = [(7,)]
    assert store.count() == 7


def test_supabase_vector_store_delete_targets_doc_id(store, fake_pg):
    store.delete("doc-9")
    sql, params = fake_pg.executed[0]
    assert sql == "DELETE FROM artemis_vectors WHERE doc_id = %s"
    assert params == ("doc-9",)


def test_supabase_vector_store_vector_literal_formats_floats():
    assert _vector_literal([0.5, 1.0, 2.25]) == "[0.5,1.0,2.25]"


def test_supabase_vector_store_redact_dsn_strips_credentials():
    redacted = _redact_dsn(FAKE_DSN)
    assert "secret" not in redacted
    assert "db.example.supabase.co" in redacted
