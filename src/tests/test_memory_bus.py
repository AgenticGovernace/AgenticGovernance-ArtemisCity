import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event, RLock
from unittest.mock import MagicMock
from uuid import UUID

import pytest

import src.integration.memory_bus as memory_bus_module
from src.integration.governance import GovernanceMonitor
from src.integration.memory_bus import MemoryBus
from src.integration.memory_decay import MemoryDecayService
from src.integration.sql_memory_store import MemoryRevision, MemoryWriteReceipt
from src.mcp.vector_store import LocalVectorStore
from src.obsidian_integration.manager import (ObsidianManager,
                                              ObsidianProjectionError)


class _InMemorySqlMemoryStore:
    """Stateful SQL-store fake for the MemoryBus write-through contract."""

    def __init__(self, *, fail_stage: bool = False, fail_delivery_ack: bool = False):
        self.fail_stage = fail_stage
        self.fail_delivery_ack = fail_delivery_ack
        self.current_by_path = {}
        self.receipts_by_key = {}
        self.outbox_status = {}
        self.failure_codes = []
        self.path_locks = {}

    def stage_write(
        self,
        *,
        relative_path,
        content,
        metadata,
        idempotency_key,
        provenance_id=None,
        source_agent=None,
    ):
        lock = self.path_locks.setdefault(relative_path, RLock())
        with lock:
            return self._stage_write_locked(
                relative_path=relative_path,
                content=content,
                metadata=metadata,
                idempotency_key=idempotency_key,
                provenance_id=provenance_id,
                source_agent=source_agent,
            )

    def _stage_write_locked(
        self,
        *,
        relative_path,
        content,
        metadata,
        idempotency_key,
        provenance_id,
        source_agent,
    ):
        if self.fail_stage:
            raise RuntimeError("SQL unavailable")

        original = self.receipts_by_key.get(idempotency_key)
        if original is not None:
            return MemoryWriteReceipt(
                revision=original.revision,
                event_id=original.event_id,
                projection_status=self.outbox_status[original.event_id],
                duplicate=True,
            )

        previous = self.current_by_path.get(relative_path)
        revision = MemoryRevision(
            record_id=f"record-{len(self.receipts_by_key) + 1}",
            memory_id=f"memory-{relative_path}",
            relative_path=relative_path,
            revision=1 if previous is None else previous.revision + 1,
            idempotency_key=idempotency_key,
            content=content,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            metadata=dict(metadata or {}),
            provenance_id=provenance_id,
            source_agent=source_agent,
            created_at=datetime.now(timezone.utc),
        )
        event_id = f"event-{len(self.receipts_by_key) + 1}"
        receipt = MemoryWriteReceipt(
            revision=revision,
            event_id=event_id,
            projection_status="pending",
            duplicate=False,
        )
        self.current_by_path[relative_path] = revision
        self.receipts_by_key[idempotency_key] = receipt
        self.outbox_status[event_id] = "pending"
        return receipt

    @contextmanager
    def projection_guard(self, relative_path):
        lock = self.path_locks.setdefault(relative_path, RLock())
        with lock:
            yield self.current_by_path.get(relative_path)

    def mark_delivered(self, event_id):
        if self.fail_delivery_ack:
            raise RuntimeError("delivery acknowledgement unavailable")
        self.outbox_status[event_id] = "delivered"

    def mark_projection_failed(self, event_id, error_code):
        self.outbox_status[event_id] = "pending"
        self.failure_codes.append((event_id, error_code))

    def get_current(self, relative_path):
        return self.current_by_path.get(relative_path)

    def list_current(self, relative_path_prefix, limit=None):
        prefix = relative_path_prefix.rstrip("/") + "/"
        revisions = [
            revision
            for path, revision in sorted(self.current_by_path.items())
            if path.startswith(prefix)
        ]
        return revisions if limit is None else revisions[:limit]

    def list_pending(self, limit=100):
        return [
            MemoryWriteReceipt(
                revision=receipt.revision,
                event_id=receipt.event_id,
                projection_status="pending",
                duplicate=receipt.duplicate,
            )
            for receipt in self.receipts_by_key.values()
            if self.outbox_status[receipt.event_id] == "pending"
        ][:limit]


def test_write_note_with_embedding_syncs_semantic_and_file(tmp_path):
    """Test that write note with embedding syncs semantic and file.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)

    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    bus = MemoryBus(manager, vector_store)

    result = bus.write_note_with_embedding(
        "Agent Outputs/sample.md",
        "hello world",
        metadata={"agent": "tester"},
    )

    assert result["status"] == "success"
    assert vector_store.count() == 1
    assert (vault / "Agent Outputs" / "sample.md").is_file()


def test_read_falls_back_to_vector_search(tmp_path):
    """Test that read falls back to vector search.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)

    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    vector_store.upsert("doc1", "mars mission overview", {"path": "notes/doc1.md"})

    bus = MemoryBus(manager, vector_store)
    results = bus.read("mars mission", max_results=1)

    assert len(results) == 1
    assert results[0]["source"] == "vector"
    assert results[0]["path"] == "notes/doc1.md"


def test_sql_failure_never_touches_obsidian(tmp_path):
    """A failed canonical commit must not produce an Obsidian projection."""
    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    sql_store = _InMemorySqlMemoryStore(fail_stage=True)
    bus = MemoryBus(manager, vector_store, sql_store=sql_store)

    with pytest.raises(RuntimeError, match="SQL unavailable"):
        bus.write_note_with_embedding("Notes/mission.md", "Canonical memory")

    assert not (vault / "Notes" / "mission.md").exists()
    assert vector_store.count() == 0


def test_obsidian_failure_keeps_sql_revision_and_returns_sync_pending(tmp_path):
    """A failed projection leaves the committed revision readable from SQL."""

    class FailingManager:
        vault_path = tmp_path

        def write_note(self, relative_path, content):
            raise OSError("vault unavailable")

        def read_note(self, relative_path):
            return None

    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    sql_store = _InMemorySqlMemoryStore()
    bus = MemoryBus(FailingManager(), vector_store, sql_store=sql_store)

    result = bus.write_note_with_embedding(
        "Notes/mission.md", "Canonical memory", idempotency_key="mission-1"
    )

    assert result["status"] == "accepted"
    assert result["sync_pending"] is True
    assert result["sql_status"] == "committed"
    assert result["obsidian_status"] == "pending"
    assert result["revision"] == 1
    assert vector_store.count() == 1
    assert bus.read("mission", relative_path="Notes/mission.md")[0]["content"] == (
        "Canonical memory"
    )


def test_embed_false_still_commits_canonical_sql(tmp_path):
    """Disabling embeddings does not skip the canonical SQL write."""
    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    sql_store = _InMemorySqlMemoryStore()
    bus = MemoryBus(manager, vector_store, sql_store=sql_store)

    result = bus.write_note_with_embedding(
        "Notes/no-embed.md", "Canonical memory", embed=False, idempotency_key="no-embed"
    )

    assert result["sql_status"] == "committed"
    assert sql_store.get_current("Notes/no-embed.md").content == "Canonical memory"
    assert vector_store.count() == 0


def test_success_marks_outbox_delivered_and_reports_synced(tmp_path):
    """A successful projection acknowledges its already-committed event."""
    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    sql_store = _InMemorySqlMemoryStore()
    bus = MemoryBus(manager, vector_store, sql_store=sql_store)

    result = bus.write_note_with_embedding(
        "Notes/mission.md", "Canonical memory", idempotency_key="mission-1"
    )

    assert result["status"] == "success"
    assert result["sync_pending"] is False
    assert result["sql_status"] == "committed"
    assert result["obsidian_status"] == "delivered"
    assert result["vector_status"] == "delivered"
    assert sql_store.outbox_status[result["event_id"]] == "delivered"


def test_duplicate_write_returns_original_revision(tmp_path):
    """An idempotent retry exposes the first canonical revision."""
    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    sql_store = _InMemorySqlMemoryStore()
    bus = MemoryBus(manager, vector_store, sql_store=sql_store)

    original = bus.write_note_with_embedding(
        "Notes/mission.md", "Canonical memory", idempotency_key="mission-1"
    )
    replay = bus.write_note_with_embedding(
        "Notes/mission.md", "Canonical memory", idempotency_key="mission-1"
    )

    assert replay["duplicate"] is True
    assert replay["record_id"] == original["record_id"]
    assert replay["revision"] == original["revision"] == 1
    assert len(sql_store.receipts_by_key) == 1


def test_generated_operation_keys_preserve_a_b_a_revision_history(tmp_path):
    """Repeated content is a new operation unless the caller reuses a key."""
    vault = tmp_path / "vault"
    vault.mkdir()
    bus = MemoryBus(
        ObsidianManager(vault_path=str(vault)),
        LocalVectorStore(db_path=str(tmp_path / "vector.db")),
        sql_store=_InMemorySqlMemoryStore(),
    )

    first = bus.write_note_with_embedding("Notes/history.md", "A")
    second = bus.write_note_with_embedding("Notes/history.md", "B")
    third = bus.write_note_with_embedding("Notes/history.md", "A")

    assert [first["revision"], second["revision"], third["revision"]] == [1, 2, 3]
    operation_keys = {
        first["idempotency_key"],
        second["idempotency_key"],
        third["idempotency_key"],
    }
    assert len(operation_keys) == 3
    assert all(
        str(UUID(result["idempotency_key"])) == result["idempotency_key"]
        for result in (first, second, third)
    )
    assert bus.sql_store.get_current("Notes/history.md").content == "A"


def test_projection_ack_failure_remains_sync_pending(tmp_path):
    """An acknowledgement failure preserves installed projection and SQL state."""
    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    sql_store = _InMemorySqlMemoryStore(fail_delivery_ack=True)
    bus = MemoryBus(manager, vector_store, sql_store=sql_store)

    result = bus.write_note_with_embedding(
        "Notes/mission.md", "Canonical memory", idempotency_key="mission-1"
    )

    assert result["status"] == "accepted"
    assert result["sync_pending"] is True
    assert result["obsidian_status"] == "pending"
    assert (vault / "Notes" / "mission.md").read_text() == "Canonical memory"
    assert vector_store.count() == 1


def test_vector_failure_after_commit_is_accepted_without_obsidian_projection(tmp_path):
    """A derived-vector failure cannot erase or misreport the SQL commit."""

    class FailingVectorStore:
        def upsert(self, *_args, **_kwargs):
            raise OSError("vector driver exposed postgres://fake-secret-host/db")

    class RecordingManager:
        vault_path = tmp_path

        def __init__(self):
            self.writes = []

        def write_note(self, relative_path, content):
            self.writes.append((relative_path, content))

    manager = RecordingManager()
    sql_store = _InMemorySqlMemoryStore()
    bus = MemoryBus(manager, FailingVectorStore(), sql_store=sql_store)

    result = bus.write_note_with_embedding(
        "Notes/vector.md", "canonical", idempotency_key="vector-1"
    )

    assert result["status"] == "accepted"
    assert result["sync_pending"] is True
    assert result["sql_status"] == "committed"
    assert result["vector_status"] == "pending"
    assert result["obsidian_status"] == "pending"
    assert manager.writes == []
    assert sql_store.get_current("Notes/vector.md").content == "canonical"
    assert sql_store.failure_codes == [(result["event_id"], "vector_projection_failed")]


def test_vector_failure_replay_retries_and_can_deliver(tmp_path):
    """Replaying a pending idempotent write retries every derived projection."""

    class FailingOnceVectorStore:
        def __init__(self):
            self.calls = 0
            self.docs = {}

        def upsert(self, doc_id, content, metadata):
            self.calls += 1
            if self.calls == 1:
                raise OSError("temporary vector failure")
            self.docs[doc_id] = (content, metadata)

    class RecordingManager:
        vault_path = tmp_path

        def __init__(self):
            self.writes = []

        def write_note(self, relative_path, content):
            self.writes.append((relative_path, content))

    manager = RecordingManager()
    vector_store = FailingOnceVectorStore()
    sql_store = _InMemorySqlMemoryStore()
    bus = MemoryBus(manager, vector_store, sql_store=sql_store)

    first = bus.write_note_with_embedding(
        "Notes/vector.md", "canonical", idempotency_key="vector-replay-1"
    )
    replay = bus.write_note_with_embedding(
        "Notes/vector.md", "canonical", idempotency_key="vector-replay-1"
    )

    assert first["status"] == "accepted"
    assert replay["status"] == "success"
    assert replay["duplicate"] is True
    assert replay["vector_status"] == "delivered"
    assert replay["obsidian_status"] == "delivered"
    assert manager.writes == [("Notes/vector.md", "canonical")]
    assert vector_store.docs["Notes/vector.md"][0] == "canonical"


def test_embed_true_replay_projects_vector_after_delivered_no_embed_replay(tmp_path):
    """A delivered vault event cannot fabricate a missing vector projection."""

    class FailingOnceVectorStore:
        def __init__(self, delegate):
            self.calls = 0
            self.delegate = delegate

        def upsert(self, doc_id, content, metadata):
            self.calls += 1
            if self.calls == 1:
                raise OSError("temporary vector failure")
            self.delegate.upsert(doc_id, content, metadata)

        def fetch_all(self):
            return self.delegate.fetch_all()

    class RecordingManager:
        vault_path = tmp_path

        def __init__(self):
            self.writes = []

        def write_note(self, relative_path, content):
            self.writes.append((relative_path, content))

    manager = RecordingManager()
    vector_store = FailingOnceVectorStore(
        LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    )
    bus = MemoryBus(manager, vector_store, sql_store=_InMemorySqlMemoryStore())

    first = bus.write_note_with_embedding(
        "Notes/vector.md", "canonical", idempotency_key="vector-sequence-1"
    )
    no_embed = bus.write_note_with_embedding(
        "Notes/vector.md",
        "canonical",
        embed=False,
        idempotency_key="vector-sequence-1",
    )
    final = bus.write_note_with_embedding(
        "Notes/vector.md", "canonical", idempotency_key="vector-sequence-1"
    )

    assert first["vector_status"] == "pending"
    assert no_embed["vector_status"] == "skipped"
    assert final["status"] == "success"
    assert final["vector_status"] == "delivered"
    assert vector_store.calls == 2
    vector_record = next(iter(vector_store.fetch_all()))
    assert vector_record.content == "canonical"
    assert len(vector_record.embedding) == 16
    assert any(component != 0.0 for component in vector_record.embedding)


def test_embed_false_reports_vector_projection_skipped(tmp_path):
    """An intentional no-embed write is distinct from a failed vector projection."""
    vault = tmp_path / "vault"
    vault.mkdir()
    bus = MemoryBus(
        ObsidianManager(vault_path=str(vault)),
        LocalVectorStore(db_path=str(tmp_path / "vector.db")),
        sql_store=_InMemorySqlMemoryStore(),
    )

    result = bus.write_note_with_embedding(
        "Notes/no-vector.md",
        "canonical",
        embed=False,
        idempotency_key="no-vector-1",
    )

    assert result["vector_status"] == "skipped"


def test_projection_guard_prevents_newer_commit_from_being_overwritten(tmp_path):
    """A cross-process-shaped path fence keeps final projections at the new head."""
    old_projection_started = Event()
    allow_old_projection = Event()
    newer_stage_entered = Event()
    newer_finished = Event()

    class InterleavingSqlStore(_InMemorySqlMemoryStore):
        def stage_write(self, **kwargs):
            if kwargs["idempotency_key"] == "race-2":
                newer_stage_entered.set()
            return super().stage_write(**kwargs)

    class InterleavingVectorStore:
        def __init__(self):
            self.docs = {}

        def upsert(self, doc_id, content, metadata):
            if content == "revision one":
                old_projection_started.set()
                assert allow_old_projection.wait(timeout=2)
            self.docs[doc_id] = (content, metadata)

    class RecordingManager:
        vault_path = tmp_path

        def __init__(self):
            self.notes = {}

        def write_note(self, relative_path, content):
            self.notes[relative_path] = content

    sql_store = InterleavingSqlStore()
    vector_store = InterleavingVectorStore()
    manager = RecordingManager()
    bus = MemoryBus(manager, vector_store, sql_store=sql_store)

    def write_old() -> None:
        bus.write_note_with_embedding(
            "Notes/race.md", "revision one", idempotency_key="race-1"
        )

    def write_new() -> None:
        bus.write_note_with_embedding(
            "Notes/race.md", "revision two", idempotency_key="race-2"
        )
        newer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        old_future = executor.submit(write_old)
        assert old_projection_started.wait(timeout=2)
        new_future = executor.submit(write_new)
        assert newer_stage_entered.wait(timeout=2)
        newer_finished.wait(timeout=0.1)
        allow_old_projection.set()
        old_future.result(timeout=2)
        new_future.result(timeout=2)

    assert sql_store.get_current("Notes/race.md").content == "revision two"
    assert manager.notes["Notes/race.md"] == "revision two"
    assert vector_store.docs["Notes/race.md"][0] == "revision two"


def test_read_exact_uses_sql_authority_and_never_stale_vault_bytes(tmp_path):
    """Exact reads expose the canonical revision even while projection is stale."""

    class StaleManager:
        vault_path = tmp_path

        def read_note(self, _relative_path):
            return "stale vault bytes"

    sql_store = _InMemorySqlMemoryStore()
    sql_store.stage_write(
        relative_path="Notes/exact.md",
        content="canonical SQL bytes",
        metadata={"kind": "canonical"},
        idempotency_key="exact-1",
    )
    bus = MemoryBus(StaleManager(), MagicMock(), sql_store=sql_store)

    result = bus.read_exact("Notes/exact.md")
    missing = bus.read_exact("Notes/missing.md")

    assert result["content"] == "canonical SQL bytes"
    assert result["metadata"] == {"kind": "canonical"}
    assert missing is None


def test_list_current_uses_sql_heads_without_reading_vault(tmp_path):
    """Canonical directory scans include SQL-only writes during projection outage."""

    class UnavailableManager:
        vault_path = tmp_path

        def list_notes_in_folder(self, _folder):
            raise AssertionError("SQL listing must not enumerate the vault")

        def read_note(self, _relative_path):
            raise AssertionError("SQL listing must not read the vault")

    sql_store = _InMemorySqlMemoryStore()
    sql_store.stage_write(
        relative_path="Agent Inputs/pending.md",
        content="status: pending",
        metadata={"kind": "task"},
        idempotency_key="pending-1",
    )
    bus = MemoryBus(UnavailableManager(), MagicMock(), sql_store=sql_store)

    records = bus.list_current("Agent Inputs")

    assert records == [
        {
            "doc_id": "Agent Inputs/pending.md",
            "relative_path": "Agent Inputs/pending.md",
            "content": "status: pending",
            "metadata": {"kind": "task"},
            "revision": 1,
            "record_id": "record-1",
            "provenance_id": None,
            "source_agent": None,
            "source": "sql",
        }
    ]


def test_sql_mode_does_not_hydrate_decay_from_derived_vector_at_boot(tmp_path):
    """Canonical startup stays available when the vector projection is offline."""

    class UnavailableVector:
        def __getattr__(self, _name):
            raise AssertionError("SQL-mode boot must not touch vector projection")

    bus = MemoryBus(
        MagicMock(vault_path=tmp_path),
        UnavailableVector(),
        memory_decay_service=MemoryDecayService(),
        sql_store=_InMemorySqlMemoryStore(),
    )

    assert bus.sql_store is not None


def test_vector_projection_ids_preserve_distinct_canonical_paths(tmp_path):
    """Spaces and underscores in SQL paths cannot collide in semantic storage."""

    class RecordingVector:
        def __init__(self):
            self.docs = {}

        def upsert(self, doc_id, content, _metadata):
            self.docs[doc_id] = content

    vault = tmp_path / "vault"
    vault.mkdir()
    vector = RecordingVector()
    bus = MemoryBus(
        ObsidianManager(str(vault)),
        vector,
        sql_store=_InMemorySqlMemoryStore(),
    )

    bus.write_note_with_embedding("Notes/a b.md", "space")
    bus.write_note_with_embedding("Notes/a_b.md", "underscore")

    assert vector.docs == {
        "Notes/a b.md": "space",
        "Notes/a_b.md": "underscore",
    }


def test_observability_and_decay_failures_cannot_reopen_delivered_projection(
    tmp_path, monkeypatch
):
    """A logger outage after commit/delivery cannot change receipt or outbox truth."""

    class RecordingVector:
        def upsert(self, _doc_id, _content, _metadata):
            return None

    class FailingRunLogger:
        def log_memory_bus_operation(self, **_kwargs):
            raise OSError("observability offline")

    class FailingGovernance:
        def record_success(self):
            raise OSError("governance offline")

    class FailingDecay:
        nodes = {}

        def register_node(self, _node):
            raise OSError("decay offline")

    vault = tmp_path / "vault"
    vault.mkdir()
    sql_store = _InMemorySqlMemoryStore()
    bus = MemoryBus(
        ObsidianManager(str(vault)),
        RecordingVector(),
        governance_monitor=FailingGovernance(),
        memory_decay_service=FailingDecay(),
        sql_store=sql_store,
    )
    monkeypatch.setattr(
        memory_bus_module, "_get_run_logger", lambda: FailingRunLogger()
    )

    result = bus.write_note_with_embedding("Notes/delivered.md", "committed")

    assert result["status"] == "success"
    assert result["sync_pending"] is False
    assert sql_store.outbox_status[result["event_id"]] == "delivered"


def test_read_results_survive_decay_and_observability_outages(tmp_path, monkeypatch):
    """Derived read hooks cannot suppress canonical results already found."""

    class FailingDecay:
        def get_node(self, _node_id):
            raise OSError("decay offline")

    class FailingRunLogger:
        def log_memory_bus_operation(self, **_kwargs):
            raise OSError("observability offline")

    vector_store = MagicMock()
    vector_store.count.return_value = 0
    sql_store = _InMemorySqlMemoryStore()
    sql_store.stage_write(
        relative_path="Notes/readable.md",
        content="canonical SQL bytes",
        metadata={"kind": "canonical"},
        idempotency_key="readable-1",
    )
    bus = MemoryBus(
        MagicMock(vault_path=tmp_path),
        vector_store,
        memory_decay_service=FailingDecay(),
        sql_store=sql_store,
    )
    monkeypatch.setattr(
        memory_bus_module, "_get_run_logger", lambda: FailingRunLogger()
    )

    results = bus.read("canonical", relative_path="Notes/readable.md")

    assert results[0]["content"] == "canonical SQL bytes"
    assert results[0]["source"] == "exact"


def test_legacy_post_replacement_error_preserves_vector_and_obsidian_state(tmp_path):
    """Legacy rollback cannot undo an already-applied atomic replacement."""

    class ReplacedThenFailedManager:
        vault_path = tmp_path

        def __init__(self):
            self.written = {}

        def write_note(self, relative_path, content):
            self.written[relative_path] = content
            raise ObsidianProjectionError(
                "directory sync failed",
                stage="parent_directory_sync",
                reason="directory_sync_failed",
                replacement_applied=True,
            )

    manager = ReplacedThenFailedManager()
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    bus = MemoryBus(manager, vector_store)

    with pytest.raises(ObsidianProjectionError):
        bus.write_note_with_embedding("Notes/mission.md", "Canonical memory")

    assert manager.written["Notes/mission.md"] == "Canonical memory"
    assert vector_store.count() == 1


def test_stale_pending_retry_is_superseded_without_overwriting_newer_projection(
    tmp_path,
):
    """Retrying an older event cannot replace the newer SQL head's projections."""

    class FlakyManager:
        vault_path = tmp_path

        def __init__(self):
            self.fail_next = True
            self.writes = []

        def write_note(self, relative_path, content):
            if self.fail_next:
                self.fail_next = False
                raise OSError("vault unavailable")
            self.writes.append((relative_path, content))

    manager = FlakyManager()
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    sql_store = _InMemorySqlMemoryStore()
    bus = MemoryBus(manager, vector_store, sql_store=sql_store)

    first = bus.write_note_with_embedding(
        "Notes/mission.md", "revision one", idempotency_key="mission-1"
    )
    second = bus.write_note_with_embedding(
        "Notes/mission.md", "revision two", idempotency_key="mission-2"
    )
    writes_before_retry = list(manager.writes)
    retry = bus.write_note_with_embedding(
        "Notes/mission.md", "revision one", idempotency_key="mission-1"
    )
    vector_record = next(iter(vector_store.fetch_all()))

    assert first["sync_pending"] is True
    assert second["revision"] == 2
    assert retry["duplicate"] is True
    assert retry["status"] == "superseded"
    assert retry["sync_pending"] is False
    assert retry["obsidian_status"] == "superseded"
    assert (
        manager.writes == writes_before_retry == [("Notes/mission.md", "revision two")]
    )
    assert vector_record.content == "revision two"
    assert first["event_id"] not in {
        receipt.event_id for receipt in sql_store.list_pending()
    }


def test_pending_idempotent_retry_projects_canonical_sql_content_and_metadata(tmp_path):
    """A retry must not project content or metadata supplied after the commit."""

    class FlakyManager:
        vault_path = tmp_path

        def __init__(self):
            self.fail_next = True
            self.writes = []

        def write_note(self, relative_path, content):
            if self.fail_next:
                self.fail_next = False
                raise OSError("vault unavailable")
            self.writes.append((relative_path, content))

    manager = FlakyManager()
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    sql_store = _InMemorySqlMemoryStore()
    bus = MemoryBus(manager, vector_store, sql_store=sql_store)

    bus.write_note_with_embedding(
        "Notes/mission.md",
        "canonical content",
        metadata={"kind": "canonical"},
        idempotency_key="mission-1",
    )
    retry = bus.write_note_with_embedding(
        "Notes/mission.md",
        "caller retry content",
        metadata={"kind": "caller-retry"},
        idempotency_key="mission-1",
    )
    vector_record = next(iter(vector_store.fetch_all()))

    assert retry["duplicate"] is True
    assert manager.writes == [("Notes/mission.md", "canonical content")]
    assert vector_record.doc_id == "Notes/mission.md"
    assert vector_record.content == "canonical content"
    assert vector_record.metadata["kind"] == "canonical"
    assert vector_record.metadata["path"] == "Notes/mission.md"
    assert "caller-retry" not in vector_record.metadata.values()


def test_vector_write_rolls_back_on_file_failure(tmp_path):
    """Test that vector write rolls back on file failure.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """

    class FailingManager:
        def __init__(self, vault_root):
            self.vault_path = vault_root

        def write_note(self, *args, **kwargs):
            raise IOError("disk full")

        def read_note(self, *args, **kwargs):
            return None

    vector_store = MagicMock()
    vector_store.upsert = MagicMock()
    vector_store.delete = MagicMock()

    bus = MemoryBus(FailingManager(tmp_path), vector_store)

    with pytest.raises(IOError):
        bus.write_note_with_embedding("note.md", "content")

    vector_store.delete.assert_called_once()


def test_rollback_failure_preserves_original_write_error_and_sanitizes_log(
    tmp_path, caplog
):
    """A failed best-effort rollback must not mask the storage failure."""
    write_error = OSError("disk full")

    class FailingManager:
        def __init__(self, vault_root):
            self.vault_path = vault_root

        def write_note(self, *args, **kwargs):
            raise write_error

    vector_store = MagicMock()
    vector_store.delete.side_effect = OSError("rollback failed\r\nforged record")
    bus = MemoryBus(FailingManager(tmp_path), vector_store)

    with caplog.at_level("WARNING"), pytest.raises(OSError) as raised:
        bus.write_note_with_embedding("notes/untrusted\nname.md", "content")

    assert raised.value is write_error
    vector_store.delete.assert_called_once_with("notes/untrusted\nname.md")
    rollback_messages = [
        record.getMessage()
        for record in caplog.records
        if "MemoryBus rollback failed" in record.getMessage()
    ]
    assert len(rollback_messages) == 1
    assert "\r" not in rollback_messages[0]
    assert "\n" not in rollback_messages[0]
    assert "forged record" in rollback_messages[0]


def test_governance_alert_on_repeated_failures(tmp_path):
    """Test that governance alert on repeated failures.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """

    class FailingManager:
        def __init__(self, vault_root):
            self.vault_path = vault_root

        def write_note(self, *args, **kwargs):
            raise IOError("disk full")

        def read_note(self, *args, **kwargs):
            return None

    vector_store = MagicMock()
    vector_store.upsert = MagicMock()
    vector_store.delete = MagicMock()

    governance = GovernanceMonitor(
        alert_threshold=1, log_path=str(tmp_path / "gov.log")
    )
    bus = MemoryBus(
        FailingManager(tmp_path), vector_store, governance_monitor=governance
    )

    with pytest.raises(IOError):
        bus.write_note_with_embedding("note.md", "content")

    assert governance.get_failure_streak() == 1


def test_memory_decay_cycle_updates_durable_vector_state(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    vector_store.upsert("notes/stale.md", "stale memory")
    vector_store.update_decay_state(
        "notes/stale.md",
        weight=0.9,
        last_access=(datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
        archived=False,
    )
    decay = MemoryDecayService(
        decay_rate=0.05,
        decay_interval_days=30,
        enable_provenance=False,
    )
    bus = MemoryBus(manager, vector_store, memory_decay_service=decay)

    result = bus.run_memory_decay_cycle()

    assert result.decayed == 1
    persisted = vector_store.get_decay_records()[0]
    assert persisted["weight"] == pytest.approx(0.8)


def test_read_restores_archived_memory_and_refreshes_access(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    manager = ObsidianManager(vault_path=str(vault))
    vector_store = LocalVectorStore(db_path=str(tmp_path / "vector.db"))
    vector_store.upsert(
        "notes/archived.md", "recover this memory", {"path": "notes/archived.md"}
    )
    old_access = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    vector_store.update_decay_state(
        "notes/archived.md",
        weight=0.5,
        last_access=old_access,
        archived=True,
    )
    decay = MemoryDecayService(enable_provenance=False)
    bus = MemoryBus(manager, vector_store, memory_decay_service=decay)

    results = bus.read("recover", max_results=1)

    assert results
    persisted = vector_store.get_decay_records()[0]
    assert persisted["archived"] is False
    assert persisted["weight"] == pytest.approx(0.55)
    assert persisted["last_access"] != old_access
