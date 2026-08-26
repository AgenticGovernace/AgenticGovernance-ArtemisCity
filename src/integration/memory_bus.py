"""Canonical memory coordination with explicit SQL-first and legacy modes.

When a SQL store is injected, PostgreSQL owns revisions and exact reads while
vector and Obsidian storage are retryable derived projections. Without a SQL
store, the compatibility path writes vector storage before the local vault.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any
from uuid import uuid4

from src.obsidian_integration import ObsidianManager
from src.obsidian_integration.manager import ObsidianProjectionError
from src.utils.helpers import logger, sanitize_for_log

from ..mcp.vector_store import LocalVectorStore
from .memory_decay import MemoryDecayService, MemoryNode
from .sql_memory_store import MemoryWriteReceipt, SqlMemoryStore

# Lazy import to avoid circular dependency
_run_logger = None


class LazyProjection:
    """Construct a derived storage adapter only when its first method is used."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._instance: Any | None = None

    def __getattr__(self, name: str) -> Any:
        if self._instance is None:
            self._instance = self._factory()
        return getattr(self._instance, name)


def _get_run_logger():
    """Lazy load run logger to avoid circular imports."""
    global _run_logger
    if _run_logger is None:
        try:
            from src.utils import get_run_logger

            _run_logger = get_run_logger()
        except Exception:
            _run_logger = None
    return _run_logger


try:
    from prometheus_client import Counter, Gauge, Histogram

    METRICS_ENABLED = True
except ImportError:  # pragma: no cover - optional dependency
    METRICS_ENABLED = False
    Counter = None  # type: ignore
    Gauge = None  # type: ignore
    Histogram = None  # type: ignore

if METRICS_ENABLED:
    # safe_metric is reimport-tolerant; without it, sys.modules.pop +
    # reimport of this module crashes with "Duplicated timeseries".
    from src.utils.prometheus_guard import safe_metric

    WRITE_TOTAL_LATENCY = safe_metric(
        Histogram,
        "artemis_memory_write_latency_ms",
        "Total memory bus write latency in milliseconds",
        buckets=[10, 50, 100, 200, 500, 1000, 2000],
    )
    WRITE_VECTOR_LATENCY = safe_metric(
        Histogram,
        "artemis_memory_vector_latency_ms",
        "Vector store write latency in milliseconds",
        buckets=[10, 50, 100, 200, 500, 1000],
    )
    WRITE_FILE_LATENCY = safe_metric(
        Histogram,
        "artemis_memory_file_latency_ms",
        "Obsidian file write latency in milliseconds",
        buckets=[10, 50, 100, 200, 500, 1000],
    )
    SYNC_LAG_GAUGE = safe_metric(
        Gauge,
        "artemis_memory_sync_lag_ms",
        "Approximate sync lag between semantic and explicit stores",
    )
    READ_SOURCE_COUNTER = safe_metric(
        Counter,
        "artemis_memory_read_total",
        "Memory bus read operations by source",
        ["source"],
    )


class MemoryBus:
    """Coordinate canonical writes, projections, and hierarchical recall.

    SQL mode commits first and fences per-path projection across processes.
    Legacy mode retains the vector-first and vault-second compatibility flow.
    """

    def __init__(
        self,
        obsidian_manager: ObsidianManager,
        vector_store: LocalVectorStore,
        search_dirs: list[str] | None = None,
        governance_monitor=None,
        memory_decay_service: MemoryDecayService | None = None,
        sql_store: SqlMemoryStore | None = None,
    ):
        self.obsidian_manager = obsidian_manager
        self.vector_store = vector_store
        self.search_dirs = search_dirs or []
        self._vault_path: Path | None = (
            None
            if sql_store is not None
            else getattr(obsidian_manager, "vault_path", None)
        )
        self.governance_monitor = governance_monitor
        self.memory_decay_service = memory_decay_service
        self.sql_store = sql_store
        self._load_decay_records()

    def write_note_with_embedding(
        self,
        relative_path: str,
        content: str,
        metadata: dict | None = None,
        embed: bool = True,
        *,
        idempotency_key: str | None = None,
        provenance_id: str | None = None,
        source_agent: str | None = None,
    ) -> dict:
        """
        Persist note content to the vector store (semantic) and Obsidian (explicit).

        Args:
            relative_path: Vault-relative note path.
            content: Markdown content to write.
            metadata: Optional metadata to store alongside the embedding.
            embed: Skip vector write when False.

        Returns:
            Dictionary with latency metrics and doc identifiers.
        """
        if self.sql_store is not None:
            return self._write_sql_first(
                relative_path,
                content,
                metadata=metadata,
                embed=embed,
                idempotency_key=idempotency_key,
                provenance_id=provenance_id,
                source_agent=source_agent,
            )

        start = time.perf_counter()
        doc_id = self._normalize_doc_id(relative_path)

        write_metadata = {"path": relative_path}
        if metadata:
            write_metadata.update(metadata)

        vector_latency_ms = None
        file_latency_ms = None

        # Write-through: semantic first, then explicit storage
        if embed:
            vector_start = time.perf_counter()
            self.vector_store.upsert(doc_id, content, write_metadata)
            vector_latency_ms = (time.perf_counter() - vector_start) * 1000
            if METRICS_ENABLED:
                WRITE_VECTOR_LATENCY.observe(vector_latency_ms)

        try:
            file_start = time.perf_counter()
            self.obsidian_manager.write_note(relative_path, content)
            file_latency_ms = (time.perf_counter() - file_start) * 1000
            if METRICS_ENABLED:
                WRITE_FILE_LATENCY.observe(file_latency_ms)
        except Exception as exc:
            # Roll back the semantic write to avoid divergence.
            # write_note is now atomic (temp file + os.replace), so a
            # partial file can't be left behind by this failure.
            if embed and not (
                isinstance(exc, ObsidianProjectionError) and exc.replacement_applied
            ):
                try:
                    self.vector_store.delete(doc_id)
                except (
                    Exception
                ) as rollback_exc:  # pragma: no cover - best-effort rollback
                    logger.warning(
                        "MemoryBus rollback failed for %s: %s",
                        sanitize_for_log(doc_id),
                        sanitize_for_log(rollback_exc),
                    )
            # Governance fires for every failed Obsidian write, including
            # embed=False — otherwise repeated no-embed failures would
            # never trip the alert streak.
            self._record_governance_failure(doc_id, relative_path, str(exc))
            raise exc

        total_latency_ms = (time.perf_counter() - start) * 1000
        if METRICS_ENABLED:
            WRITE_TOTAL_LATENCY.observe(total_latency_ms)
            # Using total latency as a proxy for sync lag budget
            SYNC_LAG_GAUGE.set(total_latency_ms)

        self._record_governance_success()
        if embed:
            self._register_decay_record(doc_id, content)

        result = {
            "status": "success",
            "doc_id": doc_id,
            "path": relative_path,
            "vector_latency_ms": vector_latency_ms,
            "file_latency_ms": file_latency_ms,
            "total_latency_ms": total_latency_ms,
        }

        # Log to run logger
        run_logger = _get_run_logger()
        if run_logger:
            run_logger.log_memory_bus_operation(
                operation="write",
                path=relative_path,
                status="success",
                vector_latency_ms=vector_latency_ms,
                file_latency_ms=file_latency_ms,
                total_latency_ms=total_latency_ms,
                metadata={
                    "doc_id": doc_id,
                    "embed": embed,
                    "content_length": len(content),
                },
            )

        return result

    def _write_sql_first(
        self,
        relative_path: str,
        content: str,
        *,
        metadata: dict | None,
        embed: bool,
        idempotency_key: str | None,
        provenance_id: str | None,
        source_agent: str | None,
    ) -> dict:
        """Commit a canonical revision before updating any projection."""
        self._validate_sql_write(relative_path, content)
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str) or not idempotency_key.strip()
        ):
            raise ValueError("idempotency_key must be a nonempty string")
        start = time.perf_counter()
        key = idempotency_key or str(uuid4())

        receipt = self.sql_store.stage_write(
            relative_path=relative_path,
            content=content,
            metadata=metadata,
            idempotency_key=key,
            provenance_id=provenance_id,
            source_agent=source_agent,
        )
        revision = receipt.revision
        doc_id = self._normalize_doc_id(revision.relative_path)
        write_metadata = dict(revision.metadata)
        write_metadata["path"] = revision.relative_path
        try:
            with self.sql_store.projection_guard(revision.relative_path) as current:
                return self._project_sql_receipt(
                    receipt,
                    current=current,
                    doc_id=doc_id,
                    write_metadata=write_metadata,
                    embed=embed,
                    start=start,
                )
        except Exception:
            self._record_governance_failure(
                doc_id, revision.relative_path, "projection_guard_failed"
            )
            self._mark_sql_projection_pending(receipt, "projection_guard_failed")
            return self._sql_write_result(
                receipt,
                doc_id=doc_id,
                vector_latency_ms=None,
                file_latency_ms=None,
                total_latency_ms=(time.perf_counter() - start) * 1000,
                status="accepted",
                obsidian_status="pending",
                vector_status="pending" if embed else "skipped",
            )

    def _project_sql_receipt(
        self,
        receipt: MemoryWriteReceipt,
        *,
        current,
        doc_id: str,
        write_metadata: dict,
        embed: bool,
        start: float,
    ) -> dict:
        """Project one receipt while its database path fence is held."""
        revision = receipt.revision
        vector_latency_ms = None
        file_latency_ms = None
        if current is not None and (
            current.record_id != revision.record_id
            or current.revision != revision.revision
        ):
            try:
                self.sql_store.mark_delivered(receipt.event_id)
            except Exception:
                self._record_governance_failure(
                    doc_id, revision.relative_path, "delivery_ack_failed"
                )
                self._mark_sql_projection_pending(receipt, "delivery_ack_failed")
                return self._sql_write_result(
                    receipt,
                    doc_id=doc_id,
                    vector_latency_ms=vector_latency_ms,
                    file_latency_ms=file_latency_ms,
                    total_latency_ms=(time.perf_counter() - start) * 1000,
                    status="accepted",
                    obsidian_status="pending",
                    vector_status="skipped",
                )
            self._record_governance_success()
            return self._sql_write_result(
                receipt,
                doc_id=doc_id,
                vector_latency_ms=vector_latency_ms,
                file_latency_ms=file_latency_ms,
                total_latency_ms=(time.perf_counter() - start) * 1000,
                status="superseded",
                obsidian_status="superseded",
                vector_status="skipped",
            )

        if embed:
            try:
                vector_start = time.perf_counter()
                self.vector_store.upsert(doc_id, revision.content, write_metadata)
                vector_latency_ms = (time.perf_counter() - vector_start) * 1000
                if METRICS_ENABLED:
                    try:
                        WRITE_VECTOR_LATENCY.observe(vector_latency_ms)
                    except Exception:  # pragma: no cover - non-authoritative metric
                        logger.warning("MemoryBus vector metrics are unavailable.")
            except Exception:
                self._record_governance_failure(
                    doc_id, revision.relative_path, "vector_projection_failed"
                )
                self._mark_sql_projection_pending(receipt, "vector_projection_failed")
                return self._sql_write_result(
                    receipt,
                    doc_id=doc_id,
                    vector_latency_ms=None,
                    file_latency_ms=None,
                    total_latency_ms=(time.perf_counter() - start) * 1000,
                    status="accepted",
                    obsidian_status="pending",
                    vector_status="pending",
                )

        try:
            file_start = time.perf_counter()
            self.obsidian_manager.write_note(revision.relative_path, revision.content)
            file_latency_ms = (time.perf_counter() - file_start) * 1000
            if METRICS_ENABLED:
                try:
                    WRITE_FILE_LATENCY.observe(file_latency_ms)
                except Exception:  # pragma: no cover - non-authoritative metric
                    logger.warning("MemoryBus file metrics are unavailable.")
        except Exception as exc:
            self._record_governance_failure(
                doc_id, revision.relative_path, "obsidian_projection_failed"
            )
            error_code = getattr(exc, "reason", "obsidian_projection_failed")
            self._mark_sql_projection_pending(receipt, error_code)
            return self._sql_write_result(
                receipt,
                doc_id=doc_id,
                vector_latency_ms=vector_latency_ms,
                file_latency_ms=file_latency_ms,
                total_latency_ms=(time.perf_counter() - start) * 1000,
                status="accepted",
                obsidian_status="pending",
                vector_status="delivered" if embed else "skipped",
            )

        try:
            self.sql_store.mark_delivered(receipt.event_id)
        except Exception:
            self._record_governance_failure(
                doc_id, revision.relative_path, "delivery_ack_failed"
            )
            self._mark_sql_projection_pending(receipt, "delivery_ack_failed")
            return self._sql_write_result(
                receipt,
                doc_id=doc_id,
                vector_latency_ms=vector_latency_ms,
                file_latency_ms=file_latency_ms,
                total_latency_ms=(time.perf_counter() - start) * 1000,
                status="accepted",
                obsidian_status="pending",
                vector_status="delivered" if embed else "skipped",
            )

        self._record_governance_success()
        if embed:
            self._register_decay_record(doc_id, revision.content)
        return self._sql_write_result(
            receipt,
            doc_id=doc_id,
            vector_latency_ms=vector_latency_ms,
            file_latency_ms=file_latency_ms,
            total_latency_ms=(time.perf_counter() - start) * 1000,
            status="success",
            obsidian_status="delivered",
            vector_status="delivered" if embed else "skipped",
        )

    def _sql_write_result(
        self,
        receipt: MemoryWriteReceipt,
        *,
        doc_id: str,
        vector_latency_ms: float | None,
        file_latency_ms: float | None,
        total_latency_ms: float,
        status: str,
        obsidian_status: str,
        vector_status: str,
    ) -> dict:
        """Return the compatibility receipt augmented with canonical identity."""
        revision = receipt.revision
        if METRICS_ENABLED:
            try:
                WRITE_TOTAL_LATENCY.observe(total_latency_ms)
                SYNC_LAG_GAUGE.set(total_latency_ms)
            except Exception:  # pragma: no cover - metrics must never affect storage
                logger.warning("MemoryBus write metrics are unavailable.")
        result = {
            "status": status,
            "doc_id": doc_id,
            "path": revision.relative_path,
            "vector_latency_ms": vector_latency_ms,
            "file_latency_ms": file_latency_ms,
            "total_latency_ms": total_latency_ms,
            "memory_id": revision.memory_id,
            "record_id": revision.record_id,
            "revision": revision.revision,
            "content_sha256": revision.content_sha256,
            "idempotency_key": revision.idempotency_key,
            "event_id": receipt.event_id,
            "sql_status": "committed",
            "obsidian_status": obsidian_status,
            "vector_status": vector_status,
            "sync_pending": obsidian_status == "pending",
            "duplicate": receipt.duplicate,
        }
        run_logger = _get_run_logger()
        if run_logger:
            try:
                run_logger.log_memory_bus_operation(
                    operation="write",
                    path=revision.relative_path,
                    status=status,
                    vector_latency_ms=vector_latency_ms,
                    file_latency_ms=file_latency_ms,
                    total_latency_ms=total_latency_ms,
                    metadata={
                        "doc_id": doc_id,
                        "memory_id": revision.memory_id,
                        "record_id": revision.record_id,
                        "revision": revision.revision,
                        "sync_pending": result["sync_pending"],
                    },
                )
            except Exception:  # pragma: no cover - receipt truth is authoritative
                logger.warning("MemoryBus run logging is unavailable.")
        return result

    def _mark_sql_projection_pending(
        self, receipt: MemoryWriteReceipt, error_code: str
    ) -> None:
        """Best-effort outbox bookkeeping that never masks a committed revision."""
        try:
            self.sql_store.mark_projection_failed(receipt.event_id, error_code)
        except Exception:  # pragma: no cover - best-effort state repair
            logger.warning(
                "MemoryBus could not mark projection pending for %s.",
                sanitize_for_log(receipt.event_id),
            )

    def read_exact(self, relative_path: str) -> dict | None:
        """Return one exact canonical or legacy note without search fallback."""
        exact_start = time.perf_counter()
        revision = (
            self.sql_store.get_current(relative_path)
            if self.sql_store is not None
            else None
        )
        if self.sql_store is not None:
            content = revision.content if revision is not None else None
        else:
            content = self.obsidian_manager.read_note(relative_path)
        if content is None:
            return None
        result = {
            "source": "exact",
            "path": relative_path,
            "content": content,
            "score": 1.0,
            "latency_ms": (time.perf_counter() - exact_start) * 1000,
        }
        if revision is not None:
            result["metadata"] = revision.metadata
            result["record_id"] = revision.record_id
            result["revision"] = revision.revision
            result["provenance_id"] = getattr(revision, "provenance_id", None)
            result["source_agent"] = getattr(revision, "source_agent", None)
        return result

    def list_current(
        self, relative_path_prefix: str, limit: int | None = None
    ) -> list[dict]:
        """List canonical SQL heads beneath one vault-relative folder prefix."""
        if self.sql_store is None:
            raise RuntimeError("canonical memory listing requires SQL mode")
        return [
            {
                "doc_id": revision.relative_path,
                "relative_path": revision.relative_path,
                "content": revision.content,
                "metadata": revision.metadata,
                "revision": revision.revision,
                "record_id": revision.record_id,
                "provenance_id": getattr(revision, "provenance_id", None),
                "source_agent": getattr(revision, "source_agent", None),
                "source": "sql",
            }
            for revision in self.sql_store.list_current(relative_path_prefix, limit)
        ]

    @staticmethod
    def _validate_sql_write(relative_path: str, content: str) -> None:
        """Reject invalid canonical writes before any persistence side effect."""
        path = PurePath(relative_path)
        if not relative_path or path.is_absolute() or ".." in path.parts:
            raise ValueError("memory path must be vault-relative")
        if not content:
            raise ValueError("memory content must not be empty")

    def read(
        self,
        query: str,
        relative_path: str | None = None,
        max_results: int = 3,
    ) -> list[dict]:
        """Retrieve knowledge via hierarchical lookup.

        Order: exact path lookup → keyword scan across configured folders →
        vector recall as a final fallback.

        Args:
            query (str): Search query or prompt text to evaluate.
            relative_path (Optional[str]): Vault-relative path associated with
                the note or record.
            max_results (int): Maximum number of retrieval results to return.

        Returns:
            List[Dict]: List containing the resulting items.
        """
        start = time.perf_counter()
        results: list[dict] = []

        if relative_path:
            exact = self.read_exact(relative_path)
            if exact is not None:
                results.append(exact)
                if METRICS_ENABLED:
                    READ_SOURCE_COUNTER.labels(source="exact").inc()

        if len(results) < max_results and self.search_dirs:
            keyword_hits = self._keyword_scan(query, max_results - len(results))
            results.extend(keyword_hits)
            if METRICS_ENABLED and keyword_hits:
                READ_SOURCE_COUNTER.labels(source="keyword").inc(len(keyword_hits))

        remaining = max_results - len(results)
        if remaining > 0 and self.vector_store.count() > 0:
            vector_start = time.perf_counter()
            vector_hits = self.vector_store.query(
                query, top_k=remaining, include_content=True
            )
            vector_latency = (time.perf_counter() - vector_start) * 1000
            for doc_id, score, metadata, content in vector_hits:
                results.append(
                    {
                        "source": "vector",
                        "path": (
                            metadata.get("path")
                            if isinstance(metadata, dict)
                            else doc_id
                        ),
                        "content": content or "",
                        "score": score,
                        "latency_ms": vector_latency,
                        "metadata": metadata,
                    }
                )
            if METRICS_ENABLED and vector_hits:
                READ_SOURCE_COUNTER.labels(source="vector").inc(len(vector_hits))

        total_latency_ms = (time.perf_counter() - start) * 1000
        for record in results:
            record.setdefault("total_latency_ms", total_latency_ms)
            path = record.get("path")
            if isinstance(path, str) and path:
                try:
                    self._record_memory_access(self._normalize_doc_id(path))
                except Exception:  # pragma: no cover - derived learning is best effort
                    logger.warning("Memory access learning is unavailable.")

        # Log to run logger
        run_logger = _get_run_logger()
        if run_logger:
            sources_used = list(set(r.get("source", "unknown") for r in results))
            try:
                run_logger.log_memory_bus_operation(
                    operation="read",
                    path=relative_path or f"query:{query[:50]}",
                    status="success",
                    total_latency_ms=total_latency_ms,
                    metadata={
                        "query_length": len(query),
                        "max_results": max_results,
                        "results_count": len(results),
                        "sources_used": sources_used,
                    },
                )
            except Exception:  # pragma: no cover - observability is best effort
                logger.warning("Memory read observability is unavailable.")

        return results

    def _load_decay_records(self) -> None:
        """Hydrate the decay service from durable vector-store metadata."""
        if self.memory_decay_service is None or self.sql_store is not None:
            return
        loader = getattr(self.vector_store, "get_decay_records", None)
        if not callable(loader):
            return
        nodes = []
        for record in loader():
            try:
                last_access = datetime.fromisoformat(record["last_access"])
                created_at = datetime.fromisoformat(record["created_at"])
            except (KeyError, TypeError, ValueError):
                now = datetime.now(timezone.utc)
                last_access = now
                created_at = now
            nodes.append(
                MemoryNode(
                    node_id=record["node_id"],
                    content=record.get("content") or "",
                    weight=float(record.get("weight", 1.0)),
                    last_access=last_access,
                    archived=bool(record.get("archived", False)),
                    created_at=created_at,
                )
            )
        self.memory_decay_service.register_nodes(nodes)

    def _register_decay_record(self, doc_id: str, content: str) -> None:
        if self.memory_decay_service is None:
            return
        try:
            self.memory_decay_service.register_node(
                MemoryNode(node_id=doc_id, content=content, weight=1.0)
            )
        except Exception:  # pragma: no cover - derived learning is non-authoritative
            logger.warning("Memory decay registration is unavailable.")

    def _persist_decay_node(self, node: MemoryNode) -> None:
        updater = getattr(self.vector_store, "update_decay_state", None)
        if callable(updater):
            updater(
                node.node_id,
                weight=node.weight,
                last_access=node.last_access.isoformat(),
                archived=node.archived,
            )

    def _record_memory_access(self, doc_id: str) -> None:
        """Reset decay state, restoring an archived memory when read."""
        if self.memory_decay_service is None:
            return
        node = self.memory_decay_service.get_node(doc_id)
        if node is None:
            return
        if node.archived:
            node = self.memory_decay_service.restore_node(doc_id)
        else:
            node = self.memory_decay_service.record_access(doc_id)
        if node is not None:
            self._persist_decay_node(node)

    def run_memory_decay_cycle(self):
        """Apply one durable decay pass to all vector-backed memories."""
        if self.memory_decay_service is None:
            return None
        before = set(self.memory_decay_service.nodes)
        result = self.memory_decay_service.run_decay_cycle()
        after = set(self.memory_decay_service.nodes)
        for node in self.memory_decay_service.all_nodes():
            self._persist_decay_node(node)
        for node_id in before - after:
            self.vector_store.delete(node_id)
        return result

    def _record_governance_failure(self, doc_id: str, path: str, error: str):
        """Notify governance monitor about a failed sync attempt."""
        if not self.governance_monitor:
            return
        event = {
            "doc_id": doc_id,
            "path": path,
            "error": error,
        }
        try:
            alert = self.governance_monitor.record_failure(event)
        except Exception:  # pragma: no cover - observability cannot alter storage truth
            logger.warning("Memory governance failure recording is unavailable.")
            return
        if alert:
            logger.error(
                "GOVERNANCE ALERT: repeated memory bus failures; rollback recommended."
            )

    def _record_governance_success(self):
        """Reset failure streak after successful operations."""
        if self.governance_monitor:
            try:
                self.governance_monitor.record_success()
            except Exception:  # pragma: no cover - observability is non-authoritative
                logger.warning("Memory governance success recording is unavailable.")

    def _keyword_scan(self, query: str, limit: int) -> list[dict]:
        """Lightweight keyword search across configured folders."""
        if not self._vault_path:
            return []

        lowered_query = query.lower()
        found: list[dict] = []

        for folder in self.search_dirs:
            folder_path = self._vault_path / folder
            if not folder_path.exists():
                continue

            for path in folder_path.rglob("*.md"):
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue

                if lowered_query in text.lower():
                    relative_path = str(path.relative_to(self._vault_path))
                    found.append(
                        {
                            "source": "keyword",
                            "path": relative_path,
                            "content": text,
                            "score": 1.0,
                        }
                    )
                    if len(found) >= limit:
                        return found
        return found

    @staticmethod
    def _normalize_doc_id(relative_path: str) -> str:
        """Use the exact canonical path as the collision-free projection id."""
        return relative_path
