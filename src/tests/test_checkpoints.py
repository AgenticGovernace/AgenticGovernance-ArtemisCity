"""Tests for governance checkpoints and rollback."""

import json
from datetime import timedelta

import pytest
from src.governance.checkpoints import (
    CheckpointStore,
    RollbackManager,
    _now,
)


@pytest.fixture
def store(tmp_path):
    return CheckpointStore(checkpoint_dir=str(tmp_path / "checkpoints"))


SNAPSHOT = {"agents": {"Alpha": {"trust_tier": "monitored", "status": "active"}}}


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
class TestCreate:
    def test_create_returns_record(self, store):
        record = store.create_checkpoint(SNAPSHOT, checkpoint_type="manual")
        assert record["checkpoint_id"]
        assert record["type"] == "manual"
        assert record["verified"] is True
        assert record["state"]["registry_snapshot"] == SNAPSHOT

    def test_create_persists_to_disk(self, store):
        record = store.create_checkpoint(SNAPSHOT)
        loaded = store.get_checkpoint(record["checkpoint_id"])
        assert loaded is not None
        assert loaded["state"]["registry_snapshot"] == SNAPSHOT

    def test_invalid_type_raises(self, store):
        with pytest.raises(ValueError, match="checkpoint_type"):
            store.create_checkpoint(SNAPSHOT, checkpoint_type="bogus")

    def test_retention_window(self, store):
        record = store.create_checkpoint(SNAPSHOT, retention_days=90)
        assert record["retention"]["days_retained"] == 90


# ---------------------------------------------------------------------------
# Listing / retrieval
# ---------------------------------------------------------------------------
class TestListGet:
    def test_get_missing_returns_none(self, store):
        assert store.get_checkpoint("nope") is None

    def test_list_newest_first(self, store):
        first = store.create_checkpoint(SNAPSHOT)
        # Force a strictly later timestamp on the second record.
        second = store.create_checkpoint({"agents": {}})
        # Patch timestamps so ordering is deterministic regardless of clock.
        ids = [r["checkpoint_id"] for r in store.list_checkpoints()]
        assert set(ids) == {first["checkpoint_id"], second["checkpoint_id"]}
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
class TestVerify:
    def test_intact_checkpoint_verifies(self, store):
        record = store.create_checkpoint(SNAPSHOT)
        assert store.verify_checkpoint(record["checkpoint_id"]) is True

    def test_tampered_checkpoint_fails(self, store):
        record = store.create_checkpoint(SNAPSHOT)
        path = store._path(record["checkpoint_id"])
        data = json.loads(path.read_text())
        data["state"]["registry_snapshot"]["agents"]["Alpha"]["status"] = "hacked"
        path.write_text(json.dumps(data))
        assert store.verify_checkpoint(record["checkpoint_id"]) is False

    def test_verify_missing_is_false(self, store):
        assert store.verify_checkpoint("ghost") is False


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------
class TestPrune:
    def test_prune_expired(self, store):
        record = store.create_checkpoint(SNAPSHOT, retention_days=1)
        # Nothing expired "now".
        assert store.prune_expired() == 0
        # Two days in the future -> expired.
        future = _now() + timedelta(days=2)
        assert store.prune_expired(now=future) == 1
        assert store.get_checkpoint(record["checkpoint_id"]) is None

    def test_locked_checkpoint_not_pruned(self, store):
        record = store.create_checkpoint(SNAPSHOT, retention_days=1)
        path = store._path(record["checkpoint_id"])
        data = json.loads(path.read_text())
        data["retention"]["locked_until"] = "2999-01-01T00:00:00.000000Z"
        path.write_text(json.dumps(data))
        future = _now() + timedelta(days=365)
        assert store.prune_expired(now=future) == 0


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------
class TestRollback:
    def test_rollback_returns_state(self, store):
        record = store.create_checkpoint(SNAPSHOT)
        mgr = RollbackManager(store)
        result = mgr.rollback_to(
            record["checkpoint_id"], initiated_by="admin", reason="error_detected"
        )
        assert result["status"] == "verified"
        assert result["restored_state"] == SNAPSHOT
        assert result["checkpoint_id"] == record["checkpoint_id"]

    def test_rollback_unknown_raises(self, store):
        mgr = RollbackManager(store)
        with pytest.raises(ValueError, match="Unknown checkpoint"):
            mgr.rollback_to("ghost", initiated_by="admin")

    def test_rollback_tampered_raises(self, store):
        record = store.create_checkpoint(SNAPSHOT)
        path = store._path(record["checkpoint_id"])
        data = json.loads(path.read_text())
        data["state"]["registry_snapshot"] = {"agents": {"Evil": {}}}
        path.write_text(json.dumps(data))
        mgr = RollbackManager(store)
        with pytest.raises(ValueError, match="integrity"):
            mgr.rollback_to(record["checkpoint_id"], initiated_by="admin")
