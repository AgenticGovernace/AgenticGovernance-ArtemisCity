"""Integration tests for Hebbian sync functionality."""
import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parents[2] / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
else:
    sys.path.remove(_src)
    sys.path.insert(0, _src)
for _key in [k for k in sys.modules if k == "integration" or k.startswith("integration.")]:
    del sys.modules[_key]

import pytest
import time
from integration.hebbian_sync import HebbianSyncService, WeightUpdate, BatchResult


class TestWeightUpdate:
    """Tests for WeightUpdate class."""

    def test_weight_update_creation(self):
        """Test creating a weight update."""
        update = WeightUpdate(
            source_node_id="agent_A",
            target_node_id="task_T1",
            new_weight=3.0,
            previous_weight=2.0,
            update_type="strengthen",
        )
        assert update.source_node_id == "agent_A"
        assert update.target_node_id == "task_T1"
        assert update.new_weight == 3.0
        assert update.previous_weight == 2.0

    def test_weight_update_defaults(self):
        """Test weight update default values."""
        update = WeightUpdate(
            source_node_id="a", target_node_id="b", new_weight=1.0
        )
        assert update.previous_weight == 0.0
        assert update.update_type == "strengthen"
        assert update.timestamp > 0

    def test_weight_update_to_dict(self):
        """Test serialization."""
        update = WeightUpdate(
            source_node_id="a", target_node_id="b", new_weight=2.0
        )
        d = update.to_dict()
        assert d["source_node_id"] == "a"
        assert d["target_node_id"] == "b"
        assert d["new_weight"] == 2.0


class TestBatchResult:
    """Tests for BatchResult class."""

    def test_batch_result_creation(self):
        """Test batch result initialization."""
        result = BatchResult(
            batch_size=10,
            successful=9,
            failed=1,
            total_latency_ms=50.0,
            avg_latency_per_update_ms=5.0,
        )
        assert result.batch_size == 10
        assert result.successful == 9
        assert result.failed == 1

    def test_batch_result_to_dict(self):
        """Test batch result serialization."""
        result = BatchResult(
            batch_size=5,
            successful=5,
            failed=0,
            total_latency_ms=10.0,
            avg_latency_per_update_ms=2.0,
        )
        d = result.to_dict()
        assert d["batch_size"] == 5
        assert d["failed"] == 0
        assert d["errors"] == []


class TestHebbianSyncService:
    """Tests for HebbianSyncService class."""

    @pytest.fixture
    def service(self):
        """Create a HebbianSyncService instance for testing."""
        return HebbianSyncService(
            batch_size=100,
            flush_interval_ms=100,
            log_dir="logs/hebbian_logs",
        )

    def test_service_initialization(self, service):
        """Test service is initialized correctly."""
        assert service.batch_size == 100
        assert service.flush_interval_ms == 100
        assert len(service._buffer) == 0

    def test_queue_update(self, service):
        """Test queuing a single update."""
        service.queue_update(
            source_node_id="agent_A",
            target_node_id="task_T1",
            new_weight=3.0,
            previous_weight=2.0,
        )
        assert len(service._buffer) == 1

    def test_queue_multiple_updates(self, service):
        """Test queuing multiple updates."""
        for i in range(10):
            service.queue_update(
                source_node_id=f"agent_{i}",
                target_node_id=f"task_{i}",
                new_weight=float(i + 1),
            )
        assert len(service._buffer) == 10

    def test_flush_sync_empty_buffer(self, service):
        """Test flushing an empty buffer returns None."""
        result = service.flush_sync()
        assert result is None

    def test_flush_sync_processes_all(self, service):
        """Test sync flush processes all buffered updates."""
        for i in range(5):
            service.queue_update(
                source_node_id=f"a{i}",
                target_node_id=f"t{i}",
                new_weight=float(i),
            )

        result = service.flush_sync()
        assert result is not None
        assert result.batch_size == 5
        assert result.successful == 5
        assert result.failed == 0
        assert len(service._buffer) == 0

    def test_flush_sync_latency_tracked(self, service):
        """Test that flush latency is recorded."""
        service.queue_update("a", "b", 1.0)
        result = service.flush_sync()
        assert result.total_latency_ms >= 0
        assert result.avg_latency_per_update_ms >= 0

    def test_should_flush_by_buffer_size(self, service):
        """Test should_flush returns True when buffer is full."""
        service.batch_size = 3
        for i in range(3):
            service.queue_update(f"a{i}", f"t{i}", 1.0)
        assert service.should_flush() is True

    def test_should_flush_by_time(self, service):
        """Test should_flush returns True after interval elapses."""
        service.queue_update("a", "b", 1.0)
        service._last_flush_time = time.time() - 1.0  # 1 second ago
        service.flush_interval_ms = 100  # 100ms
        assert service.should_flush() is True

    def test_should_flush_false_when_empty(self, service):
        """Test should_flush is False with empty buffer."""
        assert service.should_flush() is False

    def test_stats(self, service):
        """Test stats reporting."""
        for i in range(3):
            service.queue_update(f"a{i}", f"t{i}", 1.0)
        service.flush_sync()

        stats = service.get_stats()
        assert stats["buffer_size"] == 0
        assert stats["total_propagated"] == 3
        assert stats["total_errors"] == 0

    def test_register_hook(self, service):
        """Test registering a propagation hook."""
        hook_calls = []

        def my_hook(updates):
            hook_calls.append(len(updates))

        service.register_hook(my_hook)
        assert len(service._propagation_hooks) == 1

    def test_batch_log_persistence(self, service):
        """Test that batch operations are logged to disk."""
        service.queue_update("a", "b", 1.0)
        service.flush_sync()

        log_files = list(Path("logs/hebbian_logs").glob("*.jsonl"))
        assert len(log_files) >= 1

    def test_cumulative_stats_across_flushes(self, service):
        """Test that stats accumulate across multiple flushes."""
        service.queue_update("a1", "t1", 1.0)
        service.flush_sync()

        service.queue_update("a2", "t2", 2.0)
        service.flush_sync()

        stats = service.get_stats()
        assert stats["total_propagated"] == 2

    def test_buffer_cleared_after_flush(self, service):
        """Test buffer is empty after flush."""
        for i in range(5):
            service.queue_update(f"a{i}", f"t{i}", 1.0)

        service.flush_sync()
        assert len(service._buffer) == 0

    def test_update_types(self, service):
        """Test different update types are supported."""
        service.queue_update("a", "b", 3.0, 2.0, update_type="strengthen")
        service.queue_update("c", "d", 1.0, 2.0, update_type="weaken")
        service.queue_update("e", "f", 5.0, 0.0, update_type="set")

        result = service.flush_sync()
        assert result.batch_size == 3
        assert result.successful == 3

    @pytest.mark.asyncio
    async def test_propagate_weight_update_triggers_auto_flush(self, monkeypatch):
        """Async propagate flushes immediately when buffer reaches batch size."""
        service = HebbianSyncService(batch_size=1, log_dir="logs/hebbian_logs")
        flushed = {"called": 0}

        async def _fake_flush():
            flushed["called"] += 1
            return None

        monkeypatch.setattr(service, "flush", _fake_flush)
        await service.propagate_weight_update("a", "b", 1.0)
        assert flushed["called"] == 1

    @pytest.mark.asyncio
    async def test_async_flush_processes_buffer(self, service):
        """Async flush returns a BatchResult and clears buffer."""
        service.queue_update("a", "b", 1.0)
        result = await service.flush()
        assert result is not None
        assert result.batch_size == 1
        assert len(service._buffer) == 0

    def test_flush_sync_collects_failures_from_sync_pipeline(self, service, monkeypatch):
        """flush_sync records failures when sync pipeline raises."""
        service.queue_update("a", "b", 1.0)
        monkeypatch.setattr(service, "_sync_to_obsidian", lambda _: (_ for _ in ()).throw(RuntimeError("x")))

        result = service.flush_sync()
        assert result.failed == 1
        assert result.successful == 0
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_async_flush_runs_hooks_and_ignores_hook_errors(self, service):
        """Hook failures should not fail async batch processing."""
        calls = {"ok": 0}

        def _ok_hook(_updates):
            calls["ok"] += 1

        def _bad_hook(_updates):
            raise RuntimeError("hook fail")

        service.register_hook(_ok_hook)
        service.register_hook(_bad_hook)
        service.queue_update("a", "b", 1.0)
        result = await service.flush()
        assert result.successful == 1
        assert calls["ok"] == 1

    @pytest.mark.asyncio
    async def test_async_sync_targets_called(self):
        """Async sync methods call external targets when configured."""

        class _Obsidian:
            def __init__(self):
                self.calls = 0

            def update_frontmatter(self, _node, _payload):
                self.calls += 1

        class _VectorStore:
            def __init__(self):
                self.calls = 0

            def update_metadata(self, _node, _payload):
                self.calls += 1

        obsidian = _Obsidian()
        vector_store = _VectorStore()
        service = HebbianSyncService(
            obsidian_manager=obsidian,
            vector_store=vector_store,
            log_dir="logs/hebbian_logs",
        )
        update = WeightUpdate("a", "b", 1.0)

        await service._async_sync_to_obsidian(update)
        await service._async_sync_to_vector_store(update)
        assert obsidian.calls == 1
        assert vector_store.calls == 1

    @pytest.mark.asyncio
    async def test_async_sync_target_exceptions_are_swallowed(self):
        """Async target errors are best-effort and non-fatal."""

        class _Failing:
            def update_frontmatter(self, *_args, **_kwargs):
                raise RuntimeError("fail")

            def update_metadata(self, *_args, **_kwargs):
                raise RuntimeError("fail")

        service = HebbianSyncService(
            obsidian_manager=_Failing(),
            vector_store=_Failing(),
            log_dir="logs/hebbian_logs",
        )
        update = WeightUpdate("a", "b", 1.0)

        await service._async_sync_to_obsidian(update)
        await service._async_sync_to_vector_store(update)

    def test_sync_target_exceptions_are_swallowed(self):
        """Synchronous target errors are also non-fatal."""

        class _Failing:
            def update_frontmatter(self, *_args, **_kwargs):
                raise RuntimeError("fail")

            def update_metadata(self, *_args, **_kwargs):
                raise RuntimeError("fail")

        service = HebbianSyncService(
            obsidian_manager=_Failing(),
            vector_store=_Failing(),
            log_dir="logs/hebbian_logs",
        )
        update = WeightUpdate("a", "b", 1.0)
        service._sync_to_obsidian(update)
        service._sync_to_vector_store(update)

    def test_log_batch_handles_oserror(self, service, monkeypatch):
        """Disk write errors in batch logging should not raise."""
        original_open = Path.open

        def _open_with_failure(path_obj, *args, **kwargs):
            if path_obj.suffix == ".jsonl" and path_obj.parent == service._log_dir:
                raise OSError("disk full")
            return original_open(path_obj, *args, **kwargs)

        monkeypatch.setattr(Path, "open", _open_with_failure)
        update = WeightUpdate("a", "b", 1.0)
        result = BatchResult(
            batch_size=1,
            successful=1,
            failed=0,
            total_latency_ms=1.0,
            avg_latency_per_update_ms=1.0,
        )
        service._log_batch([update], result)
