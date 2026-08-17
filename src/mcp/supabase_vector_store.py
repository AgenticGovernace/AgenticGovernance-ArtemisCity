"""
Supabase pgvector backend for the Artemis vector store.

Implements the same duck-typed interface as ``LocalVectorStore``
(``upsert``, ``upsert_many``, ``delete``, ``fetch_all``, ``query``,
``count``, ``update_decay_state``, ``get_decay_records``) against a
Supabase Postgres database using the ``pgvector`` extension.

Connection is direct Postgres (psycopg2), not the PostgREST client, so the
store keeps raw-SQL semantics and real similarity search happens in the
database via the ``<=>`` cosine-distance operator instead of Python-side
cosine loops.

Configuration (environment):
    ARTEMIS_SUPABASE_DB_URL / SUPABASE_DB_URL   Postgres connection string.
    ARTEMIS_VECTOR_TABLE                        Table name (default: artemis_vectors).
    ARTEMIS_VECTOR_DIM                          Embedding dimension (default: 16,
                                                matching the built-in embedding stub).

Timestamps are stored as ISO-8601 TEXT to stay byte-compatible with the
SQLite backend: ``MemoryDecayService`` round-trips these strings verbatim,
and a timestamptz column would reformat them.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from src.utils.helpers import logger, sanitize_for_log

from .vector_store import VectorRecord, _default_embedding, _get_run_logger

try:  # pragma: no cover - exercised via import in tests
    import psycopg2
except ImportError:  # pragma: no cover
    psycopg2 = None

_VALID_TABLE_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")


def _vector_literal(embedding: List[float]) -> str:
    """Render an embedding as a pgvector text literal, e.g. '[0.1,0.2]'."""
    return "[" + ",".join(repr(float(value)) for value in embedding) + "]"


def _redact_dsn(dsn: str) -> str:
    """Strip credentials from a DSN so it is safe to log."""
    if "@" in dsn and "://" in dsn:
        scheme, rest = dsn.split("://", 1)
        return f"{scheme}://***@{rest.rsplit('@', 1)[-1]}"
    return "<redacted-dsn>"


class SupabaseVectorStore:
    """
    pgvector-backed vector store hosted on Supabase Postgres.

    Mirrors ``LocalVectorStore`` behaviour, including decay-state persistence,
    so ``MemoryBus`` and ``MemoryDecayService`` work unchanged.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        embedding_fn: Optional[Callable[[str], List[float]]] = None,
        table: Optional[str] = None,
        dim: Optional[int] = None,
    ):
        if psycopg2 is None:
            raise RuntimeError(
                "psycopg2 is required for the Supabase vector backend "
                "(install psycopg2-binary)"
            )
        self.dsn = (
            dsn or os.getenv("ARTEMIS_SUPABASE_DB_URL") or os.getenv("SUPABASE_DB_URL")
        )
        if not self.dsn:
            raise ValueError(
                "Supabase vector backend selected but no connection string set; "
                "export ARTEMIS_SUPABASE_DB_URL (or SUPABASE_DB_URL)"
            )
        self.table = (
            table or os.getenv("ARTEMIS_VECTOR_TABLE", "artemis_vectors")
        ).strip()
        if not self.table or not set(self.table.lower()) <= _VALID_TABLE_CHARS:
            raise ValueError(f"Invalid vector table name: {self.table!r}")
        self.dim = int(dim or os.getenv("ARTEMIS_VECTOR_DIM", "16"))
        if self.dim <= 0:
            raise ValueError(f"Invalid vector dimension: {self.dim}")
        self.embedding_fn = embedding_fn or _default_embedding
        self._conn = None
        self._initialize()

    # -- connection management -------------------------------------------------

    def _connection(self):
        """Return a live autocommit connection, reconnecting if needed."""
        if self._conn is None or getattr(self._conn, "closed", False):
            self._conn = psycopg2.connect(self.dsn)
            self._conn.autocommit = True
        return self._conn

    def _execute(self, sql: str, params: Tuple = ()):  # -> cursor
        try:
            cursor = self._connection().cursor()
            cursor.execute(sql, params)
            return cursor
        except psycopg2.OperationalError:
            # One reconnect attempt for dropped connections (Supabase poolers
            # recycle idle sessions); a second failure propagates.
            self._conn = None
            cursor = self._connection().cursor()
            cursor.execute(sql, params)
            return cursor

    def _initialize(self):
        self._execute("CREATE EXTENSION IF NOT EXISTS vector")
        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                doc_id TEXT PRIMARY KEY,
                embedding vector({self.dim}) NOT NULL,
                metadata JSONB,
                content TEXT,
                weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                last_access TEXT,
                archived BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TEXT
            )
            """)
        logger.info(
            "Supabase vector store ready (table=%s, dim=%d, dsn=%s)",
            self.table,
            self.dim,
            _redact_dsn(self.dsn),
        )

    # -- interface parity with LocalVectorStore --------------------------------

    def upsert(self, doc_id: str, content: str, metadata: Optional[Dict] = None):
        """Insert or replace a document with its embedding."""
        start_time = time.perf_counter()

        embedding = self.embedding_fn(content)
        now = datetime.now(timezone.utc).isoformat()
        weight = max(0.0, float((metadata or {}).get("decay_score", 1.0)))

        self._execute(
            f"""
            INSERT INTO {self.table} (
                doc_id, embedding, metadata, content, weight,
                last_access, archived, created_at
            ) VALUES (%s, %s::vector, %s, %s, %s, %s, FALSE, %s)
            ON CONFLICT (doc_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                content = EXCLUDED.content,
                weight = EXCLUDED.weight,
                last_access = EXCLUDED.last_access,
                archived = FALSE
            """,  # table validated against [a-z0-9_] in __init__; values parameterized  # nosec B608
            (
                doc_id,
                _vector_literal(embedding),
                json.dumps(metadata or {}),
                content,
                weight,
                now,
                now,
            ),
        )

        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "Upserted doc_id=%s into Supabase vector store (%.2fms)",
            sanitize_for_log(doc_id),
            latency_ms,
        )

        run_logger = _get_run_logger()
        if run_logger:
            run_logger.log_vector_operation(
                doc_id=doc_id,
                operation="upsert",
                content=content,
                embedding=embedding,
                metadata=metadata,
                latency_ms=latency_ms,
            )
            run_logger.log_db_write(
                database=_redact_dsn(self.dsn),
                table_name=self.table,
                operation="UPSERT",
                record_id=doc_id,
                data={"content_length": len(content), "embedding_dim": len(embedding)},
                latency_ms=latency_ms,
            )

    def upsert_many(self, records: Iterable[Tuple[str, str, Optional[Dict]]]):
        """Bulk upsert helper."""
        for doc_id, content, metadata in records:
            self.upsert(doc_id, content, metadata)

    def delete(self, doc_id: str):
        """Delete a document by id."""
        start_time = time.perf_counter()
        # table validated against [a-z0-9_] in __init__; values parameterized
        self._execute(
            f"DELETE FROM {self.table} WHERE doc_id = %s", (doc_id,)  # nosec B608
        )
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "Deleted doc_id=%s from Supabase vector store (%.2fms)",
            sanitize_for_log(doc_id),
            latency_ms,
        )

        run_logger = _get_run_logger()
        if run_logger:
            run_logger.log_db_write(
                database=_redact_dsn(self.dsn),
                table_name=self.table,
                operation="DELETE",
                record_id=doc_id,
                latency_ms=latency_ms,
            )

    def fetch_all(self) -> Iterable[VectorRecord]:
        """Yield every stored record, mirroring LocalVectorStore.fetch_all."""
        cursor = self._execute(
            f"SELECT doc_id, embedding::text, metadata, content, weight, "  # table validated against [a-z0-9_] in __init__; values parameterized  # nosec B608
            f"last_access, archived, created_at FROM {self.table}"
        )
        for (
            doc_id,
            embedding_text,
            metadata_value,
            content,
            weight,
            last_access,
            archived,
            created_at,
        ) in cursor.fetchall():
            if isinstance(metadata_value, str):
                metadata = json.loads(metadata_value or "{}")
            else:
                metadata = dict(metadata_value or {})
            metadata.update(
                {
                    "decay_score": float(weight),
                    "last_access": last_access,
                    "archived": bool(archived),
                }
            )
            yield VectorRecord(
                doc_id=doc_id,
                embedding=json.loads(embedding_text),
                metadata=metadata,
                content=content,
                weight=float(weight),
                last_access=last_access,
                archived=bool(archived),
                created_at=created_at,
            )

    def update_decay_state(
        self,
        doc_id: str,
        *,
        weight: float,
        last_access: str,
        archived: bool,
    ) -> bool:
        """Persist saliency, access time, and archival state for one record."""
        cursor = self._execute(
            f"UPDATE {self.table} SET weight = %s, last_access = %s, archived = %s "  # table validated against [a-z0-9_] in __init__; values parameterized  # nosec B608
            f"WHERE doc_id = %s",
            (max(0.0, float(weight)), last_access, bool(archived), doc_id),
        )
        return cursor.rowcount > 0

    def get_decay_records(self) -> List[dict]:
        """Return the persisted fields required by ``MemoryDecayService``."""
        return [
            {
                "node_id": record.doc_id,
                "content": record.content,
                "weight": record.weight,
                "last_access": record.last_access,
                "archived": record.archived,
                "created_at": record.created_at,
            }
            for record in self.fetch_all()
        ]

    def query(
        self, text: str, top_k: int = 5, include_content: bool = False
    ) -> List[Tuple]:
        """
        Return top_k results ordered by cosine similarity, computed in-database.

        pgvector's ``<=>`` operator is cosine *distance*; the score returned
        here is ``1 - distance`` so it matches LocalVectorStore's similarity.
        """
        start_time = time.perf_counter()

        query_embedding = self.embedding_fn(text)
        literal = _vector_literal(query_embedding)
        cursor = self._execute(
            f"""
            SELECT doc_id, 1 - (embedding <=> %s::vector) AS score, metadata, content
            FROM {self.table}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,  # table validated against [a-z0-9_] in __init__; values parameterized  # nosec B608
            (literal, literal, int(top_k)),
        )
        results: List[Tuple] = []
        for doc_id, score, metadata_value, content in cursor.fetchall():
            if isinstance(metadata_value, str):
                metadata = json.loads(metadata_value or "{}")
            else:
                metadata = dict(metadata_value or {})
            if include_content:
                results.append((doc_id, float(score), metadata, content))
            else:
                results.append((doc_id, float(score), metadata))

        latency_ms = (time.perf_counter() - start_time) * 1000

        run_logger = _get_run_logger()
        if run_logger:
            run_logger.log_vector_operation(
                doc_id=f"query:{text[:50]}",
                operation="query",
                content=text,
                embedding=query_embedding,
                metadata={
                    "top_k": top_k,
                    "results_count": len(results),
                    "top_score": results[0][1] if results else 0.0,
                },
                latency_ms=latency_ms,
            )

        return results

    def count(self) -> int:
        """Return the number of stored records."""
        # table validated against [a-z0-9_] in __init__; values parameterized
        cursor = self._execute(f"SELECT COUNT(*) FROM {self.table}")  # nosec B608
        (count,) = cursor.fetchone()
        return int(count)
