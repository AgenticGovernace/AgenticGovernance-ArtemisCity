"""Tests for governance checkpoints and rollback."""

import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import pytest

# Pytest gets this from conftest.py. PyCharm's unittest runner does not load
# conftest.py, so keep this file executable from src/tests as well.
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.governance.checkpoints import CheckpointStore, RollbackManager, _now


class CheckpointTestCase(unittest.TestCase):
    """Base test case with an isolated checkpoint store per test."""

    def setUp(self):
        """Create an isolated checkpoint directory for each test."""
        self._temp_dir = tempfile.TemporaryDirectory()
        checkpoint_dir = Path(self._temp_dir.name) / "checkpoints"
        self.store = CheckpointStore(checkpoint_dir=str(checkpoint_dir))

    def tearDown(self):
        """Remove the temporary checkpoint directory."""
        self._temp_dir.cleanup()


SNAPSHOT = {"agents": {"Alpha": {"trust_tier": "monitored", "status": "active"}}}


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
class TestCreate(CheckpointTestCase):
    """Provide the TestCreate abstraction used by this module."""

    def test_create_returns_record(self):
        """Test that create returns record.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT, checkpoint_type="manual")
        assert record["checkpoint_id"]
        assert record["type"] == "manual"
        assert record["verified"] is True
        assert record["state"]["registry_snapshot"] == SNAPSHOT

    def test_create_persists_to_disk(self):
        """Test that create persists to disk.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT)
        loaded = self.store.get_checkpoint(record["checkpoint_id"])
        assert loaded is not None
        assert loaded["state"]["registry_snapshot"] == SNAPSHOT

    def test_invalid_type_raises(self):
        """Test that invalid type raises.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(ValueError, match="checkpoint_type"):
            self.store.create_checkpoint(SNAPSHOT, checkpoint_type="bogus")

    def test_retention_window(self):
        """Test that retention window.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT, retention_days=90)
        assert record["retention"]["days_retained"] == 90


# ---------------------------------------------------------------------------
# Listing / retrieval
# ---------------------------------------------------------------------------
class TestListGet(CheckpointTestCase):
    """Provide the TestListGet abstraction used by this module."""

    def test_get_missing_returns_none(self):
        """Test that get missing returns none.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        assert self.store.get_checkpoint("nope") is None

    def test_list_newest_first(self):
        """Test that list newest first.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        first = self.store.create_checkpoint(SNAPSHOT)
        # Force a strictly later timestamp on the second record.
        second = self.store.create_checkpoint({"agents": {}})
        # Patch timestamps so ordering is deterministic regardless of clock.
        ids = [r["checkpoint_id"] for r in self.store.list_checkpoints()]
        assert set(ids) == {first["checkpoint_id"], second["checkpoint_id"]}
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
class TestVerify(CheckpointTestCase):
    """Provide the TestVerify abstraction used by this module."""

    def test_intact_checkpoint_verifies(self):
        """Test that intact checkpoint verifies.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT)
        assert self.store.verify_checkpoint(record["checkpoint_id"]) is True

    def test_tampered_checkpoint_fails(self):
        """Test that tampered checkpoint fails.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT)
        path = self.store._path(record["checkpoint_id"])
        data = json.loads(path.read_text())
        data["state"]["registry_snapshot"]["agents"]["Alpha"]["status"] = "hacked"
        path.write_text(json.dumps(data))
        assert self.store.verify_checkpoint(record["checkpoint_id"]) is False

    def test_verify_missing_is_false(self):
        """Test that verify missing is false.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        assert self.store.verify_checkpoint("ghost") is False

    def test_tampered_config_hash_detected(self):
        """Modifying config_snapshot must also invalidate verification.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT, config_snapshot={"flag": "on"})
        path = self.store._path(record["checkpoint_id"])
        data = json.loads(path.read_text())
        data["state"]["config_snapshot"] = {"flag": "off"}
        path.write_text(json.dumps(data))
        assert self.store.verify_checkpoint(record["checkpoint_id"]) is False


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------
class TestPrune(CheckpointTestCase):
    """Provide the TestPrune abstraction used by this module."""

    def test_prune_expired(self):
        """Test that prune expired.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT, retention_days=1)
        # Nothing expired "now".
        assert self.store.prune_expired() == 0
        # Two days in the future -> expired.
        future = _now() + timedelta(days=2)
        assert self.store.prune_expired(now=future) == 1
        assert self.store.get_checkpoint(record["checkpoint_id"]) is None

    def test_locked_checkpoint_not_pruned(self):
        """Test that locked checkpoint not pruned.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT, retention_days=1)
        path = self.store._path(record["checkpoint_id"])
        data = json.loads(path.read_text())
        data["retention"]["locked_until"] = "2999-01-01T00:00:00.000000Z"
        path.write_text(json.dumps(data))
        future = _now() + timedelta(days=365)
        assert self.store.prune_expired(now=future) == 0

    def test_expired_lock_does_not_block_prune(self):
        """Once locked_until has passed, the normal expiration check applies.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT, retention_days=1)
        path = self.store._path(record["checkpoint_id"])
        data = json.loads(path.read_text())
        # Lock that expired yesterday.
        data["retention"]["locked_until"] = "2020-01-01T00:00:00.000000Z"
        path.write_text(json.dumps(data))
        # Two days in the future -> retention also expired -> prune.
        future = _now() + timedelta(days=2)
        assert self.store.prune_expired(now=future) == 1
        assert self.store.get_checkpoint(record["checkpoint_id"]) is None


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------
class TestRollback(CheckpointTestCase):
    """Provide the TestRollback abstraction used by this module."""

    def test_rollback_returns_state(self):
        """Test that rollback returns state.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT)
        mgr = RollbackManager(self.store)
        result = mgr.rollback_to(
            record["checkpoint_id"], initiated_by="admin", reason="error_detected"
        )
        assert result["status"] == "verified"
        assert result["restored_state"] == SNAPSHOT
        assert result["checkpoint_id"] == record["checkpoint_id"]

    def test_rollback_unknown_raises(self):
        """Test that rollback unknown raises.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        mgr = RollbackManager(self.store)
        with pytest.raises(ValueError, match="Unknown checkpoint"):
            mgr.rollback_to("ghost", initiated_by="admin")

    def test_rollback_tampered_raises(self):
        """Test that rollback tampered raises.

        Args:
            store: Storage implementation used by the workflow.

        Returns:
            None: This function does not return a value.
        """
        record = self.store.create_checkpoint(SNAPSHOT)
        path = self.store._path(record["checkpoint_id"])
        data = json.loads(path.read_text())
        data["state"]["registry_snapshot"] = {"agents": {"Evil": {}}}
        path.write_text(json.dumps(data))
        mgr = RollbackManager(self.store)
        with pytest.raises(ValueError, match="integrity"):
            mgr.rollback_to(record["checkpoint_id"], initiated_by="admin")
