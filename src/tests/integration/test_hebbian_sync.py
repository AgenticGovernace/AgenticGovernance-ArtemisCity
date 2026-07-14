"""Integration tests for Hebbian sync functionality.

Tests exercise the public API of ``HebbianSyncService``, ``WeightUpdate``,
and ``BatchResult`` as defined in ``src/integration/hebbian_sync.py``.
"""

import pytest

from src.integration.hebbian_sync import BatchResult, HebbianSyncService, WeightUpdate

# ---------------------------------------------------------------------------
# WeightUpdate
# ---------------------------------------------------------------------------


class TestWeightUpdate:
    """Tests for the WeightUpdate dataclass."""

    def test_direct_construction(self):
        """All four fields can be set explicitly."""
        update = WeightUpdate(
            connection_id="agent_A->task_T1",
            old_weight=2.0,
            new_weight=3.0,
            delta=1.0,
        )
        assert update.connection_id == "agent_A->task_T1"
        assert update.old_weight == 2.0
        assert update.new_weight == 3.0
        assert update.delta == 1.0

    def test_from_weights_computes_delta(self):
        """``from_weights`` derives delta automatically."""
        update = WeightUpdate.from_weights("a->b", 1.0, 4.0)
        assert update.connection_id == "a->b"
        assert update.old_weight == 1.0
        assert update.new_weight == 4.0
        assert update.delta == pytest.approx(3.0)

    def test_from_weights_negative_delta(self):
        """Negative deltas (weight decrease) are computed correctly."""
        update = WeightUpdate.from_weights("x->y", 5.0, 2.0)
        assert update.delta == pytest.approx(-3.0)


# ---------------------------------------------------------------------------
# BatchResult
# ---------------------------------------------------------------------------


class TestBatchResult:
    """Tests for the BatchResult dataclass."""

    def test_creation(self):
        result = BatchResult(flushed=10, applied=9, latency_ms=50.0)
        assert result.flushed == 10
        assert result.applied == 9
        assert result.latency_ms == 50.0

    def test_zero_values(self):
        result = BatchResult(flushed=0, applied=0, latency_ms=0.0)
        assert result.flushed == 0
        assert result.applied == 0


# ---------------------------------------------------------------------------
# HebbianSyncService
# ---------------------------------------------------------------------------


class TestHebbianSyncService:
    """Tests for HebbianSyncService."""

    @pytest.fixture
    def service(self):
        """Service with manual flushing (no sink)."""
        return HebbianSyncService(batch_size=100, flush_interval_ms=100)

    # -- initialisation -----------------------------------------------------

    def test_service_initialization(self, service):
        assert service.batch_size == 100
        assert service.flush_interval_ms == 100
        assert service.pending() == 0

    def test_batch_size_must_be_positive(self):
        with pytest.raises(ValueError, match="batch_size must be positive"):
            HebbianSyncService(batch_size=0)

    # -- queue_update -------------------------------------------------------

    def test_queue_single_update(self, service):
        update = WeightUpdate.from_weights("a->b", 2.0, 3.0)
        service.queue_update(update)
        assert service.pending() == 1

    def test_queue_multiple_updates(self, service):
        for i in range(10):
            service.queue_update(
                WeightUpdate.from_weights(f"agent_{i}->task_{i}", 0.0, float(i + 1))
            )
        assert service.pending() == 10

    # -- flush_batch --------------------------------------------------------

    def test_flush_empty_buffer(self, service):
        result = service.flush_batch()
        assert result.flushed == 0
        assert result.applied == 0
        assert result.latency_ms >= 0

    def test_flush_clears_buffer(self, service):
        for i in range(5):
            service.queue_update(
                WeightUpdate.from_weights(f"a{i}->t{i}", 0.0, float(i))
            )
        result = service.flush_batch()
        assert result.flushed == 5
        assert service.pending() == 0

    def test_flush_latency_tracked(self, service):
        service.queue_update(WeightUpdate.from_weights("a->b", 0.0, 1.0))
        result = service.flush_batch()
        assert result.latency_ms >= 0

    def test_flush_with_sink(self):
        received = []

        def _sink(batch):
            received.extend(batch)

        service = HebbianSyncService(batch_size=10, sink=_sink)
        service.queue_update(WeightUpdate.from_weights("a->b", 0.0, 1.0))
        result = service.flush_batch()
        assert result.flushed == 1
        assert result.applied == 1
        assert len(received) == 1

    def test_flush_without_sink_applied_is_zero(self, service):
        service.queue_update(WeightUpdate.from_weights("a->b", 0.0, 1.0))
        result = service.flush_batch()
        assert result.applied == 0

    # -- propagate convenience ----------------------------------------------

    def test_propagate_queues_update(self, service):
        service.propagate("conn1", 1.0, 2.0)
        assert service.pending() == 1

    # -- auto_flush ---------------------------------------------------------

    def test_auto_flush_by_buffer_size(self):
        flushed_batches = []

        def _sink(batch):
            flushed_batches.append(list(batch))

        service = HebbianSyncService(batch_size=3, auto_flush=True, sink=_sink)
        for i in range(3):
            service.queue_update(WeightUpdate.from_weights(f"a{i}->t{i}", 0.0, 1.0))
        assert len(flushed_batches) == 1
        assert service.pending() == 0

    def test_auto_flush_by_time(self):
        flushed_batches = []

        def _sink(batch):
            flushed_batches.append(list(batch))

        service = HebbianSyncService(
            batch_size=1000, flush_interval_ms=0, auto_flush=True, sink=_sink
        )
        service.queue_update(WeightUpdate.from_weights("a->b", 0.0, 1.0))
        # flush_interval_ms=0 means every queue_update should trigger
        assert len(flushed_batches) == 1

    def test_no_auto_flush_when_disabled(self, service):
        for i in range(200):
            service.queue_update(WeightUpdate.from_weights(f"a{i}->t{i}", 0.0, 1.0))
        assert service.pending() == 200

    # -- get_stats ----------------------------------------------------------

    def test_stats_initial(self, service):
        stats = service.get_stats()
        assert stats["pending"] == 0
        assert stats["total_flushed"] == 0
        assert stats["total_batches"] == 0
        assert stats["average_batch_size"] == 0.0

    def test_stats_after_flush(self, service):
        for i in range(3):
            service.queue_update(WeightUpdate.from_weights(f"a{i}->t{i}", 0.0, 1.0))
        service.flush_batch()

        stats = service.get_stats()
        assert stats["pending"] == 0
        assert stats["total_flushed"] == 3
        assert stats["total_batches"] == 1
        assert stats["average_batch_size"] == pytest.approx(3.0)

    def test_cumulative_stats_across_flushes(self, service):
        service.queue_update(WeightUpdate.from_weights("a1->t1", 0.0, 1.0))
        service.flush_batch()

        service.queue_update(WeightUpdate.from_weights("a2->t2", 0.0, 2.0))
        service.flush_batch()

        stats = service.get_stats()
        assert stats["total_flushed"] == 2
        assert stats["total_batches"] == 2

    def test_buffer_cleared_after_flush(self, service):
        for i in range(5):
            service.queue_update(WeightUpdate.from_weights(f"a{i}->t{i}", 0.0, 1.0))
        service.flush_batch()
        assert service.pending() == 0
