"""Unit tests for the Hebbian weight sync batching service.

Naming follows docs/TEST_PLAN.md: test_<module>_<function>_<scenario>.
"""

import pytest

from src.integration.hebbian_sync import BatchResult, HebbianSyncService, WeightUpdate


@pytest.mark.unit
def test_hebbian_sync_queue_update_buffers_without_flush():
    """With auto_flush off, queueing accumulates without flushing."""
    service = HebbianSyncService()
    for i in range(5):
        flushed = service.queue_update(WeightUpdate(f"c{i}", 0.5, 0.6, 0.1))
        assert flushed is False
    assert service.pending() == 5


@pytest.mark.unit
def test_hebbian_sync_flush_batch_clears_and_counts():
    """flush_batch empties the buffer and updates cumulative counters."""
    service = HebbianSyncService()
    for i in range(10):
        service.queue_update(WeightUpdate(f"c{i}", 0.5, 0.6, 0.1))

    result = service.flush_batch()

    assert isinstance(result, BatchResult)
    assert result.flushed == 10
    assert service.pending() == 0
    assert service.total_flushed == 10
    assert service.total_batches == 1


@pytest.mark.unit
def test_hebbian_sync_flush_batch_invokes_sink_with_batch():
    """The sink receives the entire batch in a single call."""
    seen = []
    service = HebbianSyncService(sink=lambda batch: seen.append(list(batch)))
    for i in range(3):
        service.queue_update(WeightUpdate(f"c{i}", 0.5, 0.6, 0.1))

    result = service.flush_batch()

    assert result.applied == 3
    assert len(seen) == 1
    assert len(seen[0]) == 3


@pytest.mark.unit
def test_hebbian_sync_auto_flush_triggers_on_batch_size():
    """With auto_flush on, reaching batch_size flushes automatically."""
    flushes = []
    service = HebbianSyncService(
        batch_size=4, auto_flush=True, sink=lambda batch: flushes.append(len(batch))
    )

    triggered = [
        service.queue_update(WeightUpdate(f"c{i}", 0.5, 0.6, 0.1)) for i in range(4)
    ]

    assert triggered[-1] is True
    assert service.pending() == 0
    assert flushes == [4]


@pytest.mark.unit
def test_hebbian_sync_flush_empty_buffer_is_noop():
    """Flushing an empty buffer counts no batch and returns zero flushed."""
    service = HebbianSyncService()
    result = service.flush_batch()
    assert result.flushed == 0
    assert result.applied == 0
    assert service.total_batches == 0


@pytest.mark.unit
def test_hebbian_sync_weight_update_from_weights_computes_delta():
    """from_weights derives delta as new - old."""
    update = WeightUpdate.from_weights("origin->target", 0.4, 0.7)
    assert update.delta == pytest.approx(0.3)
    assert update.connection_id == "origin->target"
