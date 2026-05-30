"""Checkpoint storage and rollback for the governance layer.

Implements the checkpoint structure described in GOVERNANCE.md: each
checkpoint is a JSON document under a checkpoint directory, carrying a
content hash for integrity verification and a retention window. The
``RollbackManager`` validates a checkpoint's integrity before returning its
captured state for restoration.

This is the data-model / persistence layer only. Wiring a rollback into the
live registry / kernel is deferred until those components expose a restore
hook; ``RollbackManager.rollback_to`` therefore returns the verified state
and logs the request rather than mutating a running system.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from src.utils.helpers import logger

CHECKPOINT_TYPES = ("deployment", "scheduled", "manual")
DEFAULT_RETENTION_DAYS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hash_state(state: dict) -> str:
    """Stable SHA-256 over a state dict (sorted keys for determinism)."""
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class CheckpointStore:
    """JSON-file-backed store for system checkpoints."""

    def __init__(self, checkpoint_dir: str = "data/checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, checkpoint_id: str) -> Path:
        return self.checkpoint_dir / f"{checkpoint_id}.json"

    def create_checkpoint(
        self,
        registry_snapshot: dict,
        checkpoint_type: str = "manual",
        metadata: Optional[dict] = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        config_snapshot: Optional[dict] = None,
    ) -> dict:
        """Persist a checkpoint and return its record.

        ``registry_snapshot`` and the optional ``config_snapshot`` are hashed
        for integrity. The retention window is computed from ``retention_days``.
        """
        if checkpoint_type not in CHECKPOINT_TYPES:
            raise ValueError(
                f"Invalid checkpoint_type {checkpoint_type!r}; "
                f"expected one of {CHECKPOINT_TYPES}"
            )

        checkpoint_id = str(uuid.uuid4())
        created = _now()
        config_snapshot = config_snapshot or {}

        record = {
            "checkpoint_id": checkpoint_id,
            "timestamp": _iso(created),
            "type": checkpoint_type,
            "metadata": metadata or {},
            "state": {
                "system_hash": _hash_state(
                    {"registry": registry_snapshot, "config": config_snapshot}
                ),
                "config_hash": _hash_state(config_snapshot),
                "registry_snapshot": registry_snapshot,
                "config_snapshot": config_snapshot,
            },
            "retention": {
                "expires_at": _iso(created + timedelta(days=retention_days)),
                "days_retained": retention_days,
                "locked_until": None,
            },
            "verified": True,
        }

        tmp_path = self._path(checkpoint_id).with_name(f"{checkpoint_id}.json.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(record, fh, indent=2)
            tmp_path.replace(self._path(checkpoint_id))
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        logger.info(
            "Created %s checkpoint %s (retain %dd)",
            checkpoint_type,
            checkpoint_id,
            retention_days,
        )
        return record

    def get_checkpoint(self, checkpoint_id: str) -> Optional[dict]:
        """Load a checkpoint record, or None if it does not exist."""
        path = self._path(checkpoint_id)
        if not path.is_file():
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def list_checkpoints(self) -> List[dict]:
        """Return all checkpoint records, newest first."""
        records = []
        for path in self.checkpoint_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    records.append(json.load(fh))
            except (json.JSONDecodeError, OSError):
                logger.warning("Skipping unreadable checkpoint: %s", path.name)
        return sorted(records, key=lambda r: r.get("timestamp", ""), reverse=True)

    def verify_checkpoint(self, checkpoint_id: str) -> bool:
        """Recompute the integrity hash and compare against the stored value."""
        record = self.get_checkpoint(checkpoint_id)
        if record is None:
            return False
        state = record.get("state", {})
        recomputed = _hash_state(
            {
                "registry": state.get("registry_snapshot", {}),
                "config": state.get("config_snapshot", {}),
            }
        )
        return recomputed == state.get("system_hash")

    def prune_expired(self, now: Optional[datetime] = None) -> int:
        """Delete checkpoints whose retention window has passed. Returns count."""
        now = now or _now()
        removed = 0
        for record in self.list_checkpoints():
            expires_at = record.get("retention", {}).get("expires_at")
            locked_until = record.get("retention", {}).get("locked_until")
            if locked_until is not None:
                continue
            if expires_at and expires_at < _iso(now):
                self._path(record["checkpoint_id"]).unlink(missing_ok=True)
                removed += 1
        if removed:
            logger.info("Pruned %d expired checkpoint(s)", removed)
        return removed


class RollbackManager:
    """Validates and initiates rollbacks against a :class:`CheckpointStore`."""

    def __init__(self, store: CheckpointStore):
        self.store = store

    def rollback_to(
        self,
        checkpoint_id: str,
        initiated_by: str,
        reason: str = "manual_request",
        details: str = "",
    ) -> dict:
        """Validate checkpoint integrity and return the state to restore.

        Raises ``ValueError`` if the checkpoint is missing or fails integrity
        verification. Returns a rollback record including the verified
        ``registry_snapshot`` for the caller to apply.
        """
        record = self.store.get_checkpoint(checkpoint_id)
        if record is None:
            raise ValueError(f"Unknown checkpoint: {checkpoint_id!r}")
        if not self.store.verify_checkpoint(checkpoint_id):
            raise ValueError(
                f"Checkpoint {checkpoint_id!r} failed integrity verification"
            )

        rollback_id = str(uuid.uuid4())
        logger.info(
            "Rollback %s to checkpoint %s by %s (reason: %s)",
            rollback_id,
            checkpoint_id,
            initiated_by,
            reason,
        )
        return {
            "rollback_id": rollback_id,
            "checkpoint_id": checkpoint_id,
            "initiated_by": initiated_by,
            "reason": reason,
            "details": details,
            "timestamp": _iso(_now()),
            "status": "verified",
            "restored_state": record["state"]["registry_snapshot"],
        }
