"""
Lightweight vector store backed by SQLite to mimic pgvector-style storage locally.

Embeddings are stored as JSON-encoded float arrays; cosine similarity is used for retrieval.
This module is framework-agnostic and can be swapped for a real pgvector backend later.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from ..utils.helpers import logger

# Lazy import to avoid circular dependency
_run_logger = None


def _get_run_logger():
    """Lazy load run logger to avoid circular imports."""
    global _run_logger
    if _run_logger is None:
        try:
            from ..utils.run_logger import get_run_logger

            _run_logger = get_run_logger()
        except Exception:
            _run_logger = None
    return _run_logger


def _default_embedding(text: str, dim: int = 16) -> List[float]:
    """
    Deterministic, lightweight embedding stub (hash-bucketed character n-grams).
    This is a placeholder for a real embedding model; it keeps tests and local usage self-contained.
    """
    buckets = [0.0] * dim
    for idx, ch in enumerate(text):
        bucket = (ord(ch) + idx) % dim
        buckets[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in buckets)) or 1.0
    return [v / norm for v in buckets]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)


@dataclass
class VectorRecord:
    doc_id: str
    embedding: List[float]
    metadata: Dict
    content: str


class LocalVectorStore:
    """
    SQLite-backed vector store that mirrors pgvector-like usage.
    Stores embeddings as JSON; retrieval computes cosine similarity in Python.
    """

    def __init__(
        self,
        db_path: str = "data/vector_store.db",
        embedding_fn: Optional[Callable[[str], List[float]]] = None,
    ):
        self.db_path = db_path
        self.embedding_fn = embedding_fn or _default_embedding
        self._ensure_db_directory()
        self._initialize()

    def _ensure_db_directory(self):
        if self.db_path == ":memory:":
            return
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info("Created vector store directory at %s", db_dir)

    def _initialize(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    doc_id TEXT PRIMARY KEY,
                    embedding TEXT NOT NULL,
                    metadata TEXT,
                    content TEXT
                )
                """
            )
            conn.commit()

    def upsert(self, doc_id: str, content: str, metadata: Optional[Dict] = None):
        """Insert or replace a document with its embedding."""
        start_time = time.perf_counter()

        embedding = self.embedding_fn(content)
        metadata_json = json.dumps(metadata or {})
        embedding_json = json.dumps(embedding)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO vectors (doc_id, embedding, metadata, content)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    embedding = excluded.embedding,
                    metadata = excluded.metadata,
                    content = excluded.content
                """,
                (doc_id, embedding_json, metadata_json, content),
            )
            conn.commit()

        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "Upserted doc_id=%s into vector store (%.2fms)", doc_id, latency_ms
        )

        # Log to run logger
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
                database=self.db_path,
                table_name="vectors",
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
        start_time = time.perf_counter()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM vectors WHERE doc_id = ?", (doc_id,))
            conn.commit()

        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.debug("Deleted doc_id=%s from vector store (%.2fms)", doc_id, latency_ms)

        # Log to run logger
        run_logger = _get_run_logger()
        if run_logger:
            run_logger.log_db_write(
                database=self.db_path,
                table_name="vectors",
                operation="DELETE",
                record_id=doc_id,
                latency_ms=latency_ms,
            )

    def fetch_all(self) -> Iterable[VectorRecord]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT doc_id, embedding, metadata, content FROM vectors"
            )
            for doc_id, embedding_json, metadata_json, content in cursor.fetchall():
                yield VectorRecord(
                    doc_id=doc_id,
                    embedding=json.loads(embedding_json),
                    metadata=json.loads(metadata_json or "{}"),
                    content=content,
                )

    def query(
        self, text: str, top_k: int = 5, include_content: bool = False
    ) -> List[Tuple]:
        """
        Return top_k similarity results ordered by cosine similarity.

        Args:
            text: Query text to embed and compare.
            top_k: Number of results to return.
            include_content: When True, include stored document content in results.

        Returns:
            List of tuples:
                (doc_id, score, metadata) when include_content is False
                (doc_id, score, metadata, content) when include_content is True
        """
        start_time = time.perf_counter()

        query_embedding = self.embedding_fn(text)
        scored: List[Tuple[str, float, Dict]] = []
        for record in self.fetch_all():
            score = _cosine_similarity(query_embedding, record.embedding)
            if include_content:
                scored.append((record.doc_id, score, record.metadata, record.content))
            else:
                scored.append((record.doc_id, score, record.metadata))
        scored.sort(key=lambda item: item[1], reverse=True)
        results = scored[:top_k]

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Log to run logger
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM vectors")
            (count,) = cursor.fetchone()
            return count
