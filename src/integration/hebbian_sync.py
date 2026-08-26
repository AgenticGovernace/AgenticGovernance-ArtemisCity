"""Hebbian weight synchronization with batching.

Realizes the "Hebbian Learning Synchronization" item from the whitebook /
project update plan (Part 1.1, Priority 3): when link weights change in the
Hebbian layer, the saliency updates must propagate to the secondary store
(vector metadata / Supabase ranking) **efficiently**. Rather than issuing one
write per weight change, updates are accumulated and flushed as a batch — by
size (``batch_size`` updates) or by time (``flush_interval_ms``).

The service is store-agnostic: it buffers :class:`WeightUpdate` records and, on
flush, hands the whole batch to an optional ``sink`` callback. Callers wire the
sink to whatever backing store they use (e.g. upsert saliency into the vector
store metadata). With no sink it is a pure in-memory batcher — the exact shape
exercised by ``benchmarks/bench_memory_ops.py`` (``queue_update`` then
``flush_batch``).

Import tolerance mirrors :mod:`memory_decay`: works whether imported as
``src.integration.hebbian_sync`` or ``integration.hebbian_sync``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

try:  # repo root on path (tests / app): `src` is a package
    from src.utils.helpers import logger
except ImportError:  # pragma: no cover - exercised under benchmark/bare layouts
    try:  # src/ itself on path (benchmark): `utils` is top-level
        from utils.helpers import logger
    except ImportError:  # last resort: never fail to import over logging
        import logging

        logger = logging.getLogger("artemis.hebbian_sync")


@dataclass
class WeightUpdate:
    """A single pending weight change for one connection.

    Attributes:
        connection_id: Identifier for the connection (e.g. ``"origin->target"``).
        old_weight: Weight before the change.
        new_weight: Weight after the change.
        delta: Signed change applied (``new_weight - old_weight``).
    """

    connection_id: str
    old_weight: float
    new_weight: float
    delta: float

    @classmethod
    def from_weights(
        cls, connection_id: str, old_weight: float, new_weight: float
    ) -> WeightUpdate:
        """Build an update, computing ``delta`` from old/new weights.

        Args:
            connection_id: Identifier for the connection.
            old_weight: Weight before the change.
            new_weight: Weight after the change.

        Returns:
            A populated :class:`WeightUpdate`.
        """
        return cls(connection_id, old_weight, new_weight, new_weight - old_weight)


@dataclass
class BatchResult:
    """Outcome of a single :meth:`HebbianSyncService.flush_batch` call.

    Attributes:
        flushed: Number of updates removed from the buffer this flush.
        applied: Number of updates successfully handed to the sink.
        latency_ms: Wall-clock time spent flushing, in milliseconds.
    """

    flushed: int
    applied: int
    latency_ms: float


# A sink receives the whole batch so it can persist it in one operation.
BatchSink = Callable[[list[WeightUpdate]], None]


class HebbianSyncService:
    """Accumulate weight updates and flush them to a sink in batches."""

    def __init__(
        self,
        batch_size: int = 100,
        flush_interval_ms: float = 100.0,
        sink: BatchSink | None = None,
        auto_flush: bool = False,
    ) -> None:
        """Initialize the sync service.

        Args:
            batch_size: Update count that triggers an auto-flush (when enabled).
            flush_interval_ms: Elapsed time that triggers an auto-flush (when
                enabled), in milliseconds.
            sink: Optional callback invoked with the batch on each flush.
            auto_flush: When True, :meth:`queue_update` flushes automatically once
                ``batch_size`` or ``flush_interval_ms`` is reached. When False
                (the default, and what the benchmark uses), flushing is manual.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms
        self.sink = sink
        self.auto_flush = auto_flush

        self._buffer: list[WeightUpdate] = []
        self._last_flush = time.perf_counter()
        self.total_flushed = 0
        self.total_batches = 0

    def queue_update(self, update: WeightUpdate) -> bool:
        """Add an update to the buffer.

        Args:
            update: The :class:`WeightUpdate` to enqueue.

        Returns:
            True if this call triggered an auto-flush, else False.
        """
        self._buffer.append(update)
        if self.auto_flush:
            elapsed_ms = (time.perf_counter() - self._last_flush) * 1000
            if (
                len(self._buffer) >= self.batch_size
                or elapsed_ms >= self.flush_interval_ms
            ):
                self.flush_batch()
                return True
        return False

    def propagate(
        self, connection_id: str, old_weight: float, new_weight: float
    ) -> bool:
        """Convenience: build a :class:`WeightUpdate` and queue it.

        Args:
            connection_id: Identifier for the connection.
            old_weight: Weight before the change.
            new_weight: Weight after the change.

        Returns:
            True if this call triggered an auto-flush, else False.
        """
        return self.queue_update(
            WeightUpdate.from_weights(connection_id, old_weight, new_weight)
        )

    def flush_batch(self) -> BatchResult:
        """Flush the buffered updates to the sink and clear the buffer.

        Returns:
            A :class:`BatchResult` with the flushed/applied counts and latency.
        """
        start = time.perf_counter()
        batch = self._buffer
        self._buffer = []

        applied = 0
        if self.sink is not None and batch:
            try:
                self.sink(batch)
                applied = len(batch)
            except Exception:  # pragma: no cover - defensive; sink owns its errors
                logger.exception(
                    "Hebbian sync sink failed for batch of %d update(s)", len(batch)
                )

        latency_ms = (time.perf_counter() - start) * 1000
        self._last_flush = time.perf_counter()
        self.total_flushed += len(batch)
        if batch:
            self.total_batches += 1

        if batch:
            logger.debug(
                "Hebbian sync flushed %d update(s) in %.2fms", len(batch), latency_ms
            )
        return BatchResult(flushed=len(batch), applied=applied, latency_ms=latency_ms)

    def pending(self) -> int:
        """Return the number of updates currently buffered."""
        return len(self._buffer)

    def get_stats(self) -> dict:
        """Return cumulative batching statistics.

        Returns:
            Dict with ``pending``, ``total_flushed``, ``total_batches`` and the
            running ``average_batch_size``.
        """
        avg = self.total_flushed / self.total_batches if self.total_batches else 0.0
        return {
            "pending": len(self._buffer),
            "total_flushed": self.total_flushed,
            "total_batches": self.total_batches,
            "average_batch_size": avg,
        }
