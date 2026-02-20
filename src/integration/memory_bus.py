"""
Hybrid memory bus that keeps Obsidian (explicit, auditable memory) and the
vector store (fast semantic recall) in sync.

Implements a write-through protocol and a simple read hierarchy inspired by
the architecture described in Agent_Architecture__From_Prototypes_to_Production.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

from mcp.vector_store import LocalVectorStore
from obsidian_integration.manager import ObsidianManager
from utils.helpers import logger

# Lazy import to avoid circular dependency
_run_logger = None


def _get_run_logger():
    """Lazy load run logger to avoid circular imports."""
    global _run_logger
    if _run_logger is None:
        try:
            from utils.run_logger import get_run_logger

            _run_logger = get_run_logger()
        except Exception:
            _run_logger = None
    return _run_logger


try:
    from prometheus_client import Counter, Gauge, Histogram

    METRICS_ENABLED = True
except ImportError:  # pragma: no cover - optional dependency
    METRICS_ENABLED = False
    Counter = Gauge = Histogram = None

if METRICS_ENABLED:
    WRITE_TOTAL_LATENCY = Histogram(
        "artemis_memory_write_latency_ms",
        "Total memory bus write latency in milliseconds",
        buckets=[10, 50, 100, 200, 500, 1000, 2000],
    )
    WRITE_VECTOR_LATENCY = Histogram(
        "artemis_memory_vector_latency_ms",
        "Vector store write latency in milliseconds",
        buckets=[10, 50, 100, 200, 500, 1000],
    )
    WRITE_FILE_LATENCY = Histogram(
        "artemis_memory_file_latency_ms",
        "Obsidian file write latency in milliseconds",
        buckets=[10, 50, 100, 200, 500, 1000],
    )
    SYNC_LAG_GAUGE = Gauge(
        "artemis_memory_sync_lag_ms",
        "Approximate sync lag between semantic and explicit stores",
    )
    READ_SOURCE_COUNTER = Counter(
        "artemis_memory_read_total",
        "Memory bus read operations by source",
        ["source"],
    )


class MemoryBus:
    """
    Coordinates knowledge writes and reads across Obsidian and the vector store.

    - Writes go to the vector store first, then Obsidian (write-through).
    - Reads prioritize exact note lookup, then lightweight keyword scan, then vector recall.
    """

    def __init__(
        self,
        obsidian_manager: ObsidianManager,
        vector_store: LocalVectorStore,
        search_dirs: Optional[List[str]] = None,
        governance_monitor=None,
    ):
        self.obsidian_manager = obsidian_manager
        self.vector_store = vector_store
        self.search_dirs = search_dirs or []
        self._vault_path: Optional[Path] = getattr(obsidian_manager, "vault_path", None)
        self.governance_monitor = governance_monitor

    def write_note_with_embedding(
        self,
        relative_path: str,
        content: str,
        metadata: Optional[Dict] = None,
        embed: bool = True,
    ) -> Dict:
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
            # Roll back semantic write to avoid divergence
            if embed:
                try:
                    self.vector_store.delete(doc_id)
                except (
                    Exception
                ) as rollback_exc:  # pragma: no cover - best-effort rollback
                    logger.warning(
                        f"MemoryBus rollback failed for {doc_id}: {rollback_exc}"
                    )
                self._record_governance_failure(doc_id, relative_path, str(exc))
            raise exc

        total_latency_ms = (time.perf_counter() - start) * 1000
        if METRICS_ENABLED:
            WRITE_TOTAL_LATENCY.observe(total_latency_ms)
            # Using total latency as a proxy for sync lag budget
            SYNC_LAG_GAUGE.set(total_latency_ms)

        self._record_governance_success()

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

    def read(
        self,
        query: str,
        relative_path: Optional[str] = None,
        max_results: int = 3,
    ) -> List[Dict]:
        """
        Retrieve knowledge via hierarchical lookup.

        Order: exact path lookup → keyword scan across configured folders →
        vector recall as a final fallback.
        """
        start = time.perf_counter()
        results: List[Dict] = []

        if relative_path:
            exact_start = time.perf_counter()
            content = self.obsidian_manager.read_note(relative_path)
            if content:
                results.append(
                    {
                        "source": "exact",
                        "path": relative_path,
                        "content": content,
                        "score": 1.0,
                        "latency_ms": (time.perf_counter() - exact_start) * 1000,
                    }
                )
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

        # Log to run logger
        run_logger = _get_run_logger()
        if run_logger:
            sources_used = list(set(r.get("source", "unknown") for r in results))
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

        return results

    def _record_governance_failure(self, doc_id: str, path: str, error: str):
        """Notify governance monitor about a failed sync attempt."""
        if not self.governance_monitor:
            return
        event = {
            "doc_id": doc_id,
            "path": path,
            "error": error,
        }
        alert = self.governance_monitor.record_failure(event)
        if alert:
            logger.error(
                "GOVERNANCE ALERT: repeated memory bus failures; rollback recommended."
            )

    def _record_governance_success(self):
        """Reset failure streak after successful operations."""
        if self.governance_monitor:
            self.governance_monitor.record_success()

    def _keyword_scan(self, query: str, limit: int) -> List[Dict]:
        """Lightweight keyword search across configured folders."""
        if not self._vault_path:
            return []

        lowered_query = query.lower()
        found: List[Dict] = []

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
        """Create a stable doc id from a vault-relative path."""
        return relative_path.replace(" ", "_")
