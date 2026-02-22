"""
Rollback Manager — git-style versioned checkpointing for Artemis City.

Provides:
- Create named checkpoints of system state (agent registry, kernel config,
  governance rules)
- Rollback to any previous checkpoint
- Checkpoint pruning and retention policies
- Provenance logging for all rollback operations

Part of the Artemis City Governance Layer.
"""

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from utils.helpers import logger


@dataclass
class Checkpoint:
    """Represents a point-in-time snapshot of system state."""

    id: str
    label: str
    timestamp: float
    data: Dict
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "label": self.label,
            "timestamp": self.timestamp,
            "created_at": datetime.fromtimestamp(self.timestamp).isoformat(),
            "metadata": self.metadata,
            "data_keys": list(self.data.keys()),
        }


class RollbackManager:
    """
    Manages versioned checkpoints and rollback operations.

    Checkpoints capture:
    - Agent registry state (scores, capabilities)
    - Kernel configuration (routing weights, policies)
    - Governance rules (approval thresholds, whitelists)
    - Hebbian weight snapshots

    Retention policy: keep last N checkpoints (default: 50).
    """

    DEFAULT_MAX_CHECKPOINTS = 50

    def __init__(
        self,
        checkpoint_dir: str = "data/checkpoints",
        max_checkpoints: int = DEFAULT_MAX_CHECKPOINTS,
    ):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.max_checkpoints = max_checkpoints
        self.checkpoint_history: List[str] = []
        self._rollback_log: List[Dict] = []

        # Load existing checkpoint history from disk
        self._load_checkpoint_index()

    def create_checkpoint(
        self,
        label: str,
        state: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        Create a versioned checkpoint of current system state.

        Args:
            label: Human-readable label for the checkpoint (e.g., "pre_v0.2_deploy")
            state: Dictionary containing system state to snapshot.
                   Expected keys: agent_registry, kernel_config, governance_rules,
                   hebbian_snapshot
            metadata: Optional metadata (e.g., trigger reason, proposing agent)

        Returns:
            Checkpoint ID string.
        """
        checkpoint_id = f"{label}_{int(time.time())}"
        state = state or {}
        metadata = metadata or {}

        checkpoint_data = {
            "id": checkpoint_id,
            "label": label,
            "timestamp": time.time(),
            "created_at": datetime.utcnow().isoformat(),
            "metadata": metadata,
            "state": {
                "agent_registry": state.get("agent_registry", {}),
                "kernel_config": state.get("kernel_config", {}),
                "governance_rules": state.get("governance_rules", {}),
                "hebbian_snapshot": state.get("hebbian_snapshot", {}),
            },
        }

        # Save checkpoint to disk
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        with checkpoint_path.open("w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2)

        self.checkpoint_history.append(checkpoint_id)
        self._save_checkpoint_index()

        # Enforce retention policy
        self._enforce_retention()

        logger.info(f"[ROLLBACK] Checkpoint created: {checkpoint_id}")
        return checkpoint_id

    def rollback_to(self, checkpoint_id: str) -> Dict:
        """
        Restore system state from a checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to restore.

        Returns:
            Dictionary containing the restored state.

        Raises:
            FileNotFoundError: If checkpoint doesn't exist.
        """
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_id}.json"

        if not checkpoint_path.exists():
            raise FileNotFoundError(
                f"Checkpoint '{checkpoint_id}' not found at {checkpoint_path}"
            )

        with checkpoint_path.open("r", encoding="utf-8") as f:
            checkpoint_data = json.load(f)

        state = checkpoint_data.get("state", {})

        # Log the rollback operation
        rollback_event = {
            "event": "rollback",
            "checkpoint_id": checkpoint_id,
            "checkpoint_label": checkpoint_data.get("label"),
            "checkpoint_timestamp": checkpoint_data.get("timestamp"),
            "rollback_timestamp": datetime.utcnow().isoformat(),
            "state_keys_restored": list(state.keys()),
        }
        self._rollback_log.append(rollback_event)
        self._persist_rollback_event(rollback_event)

        logger.info(f"[ROLLBACK] Restored to checkpoint: {checkpoint_id}")
        return state

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load a specific checkpoint without applying it."""
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        if not checkpoint_path.exists():
            return None

        with checkpoint_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return Checkpoint(
            id=data["id"],
            label=data["label"],
            timestamp=data["timestamp"],
            data=data.get("state", {}),
            metadata=data.get("metadata", {}),
        )

    def list_checkpoints(self) -> List[Dict]:
        """List all available checkpoints with metadata."""
        checkpoints = []
        for cp_id in self.checkpoint_history:
            cp_path = self.checkpoint_dir / f"{cp_id}.json"
            if cp_path.exists():
                try:
                    with cp_path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    checkpoints.append({
                        "id": data.get("id"),
                        "label": data.get("label"),
                        "timestamp": data.get("timestamp"),
                        "created_at": data.get("created_at"),
                        "metadata": data.get("metadata", {}),
                        "state_keys": list(data.get("state", {}).keys()),
                    })
                except (json.JSONDecodeError, OSError):
                    continue
        return checkpoints

    def get_latest_checkpoint_id(self) -> Optional[str]:
        """Return the most recent checkpoint ID, or None."""
        return self.checkpoint_history[-1] if self.checkpoint_history else None

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Remove a checkpoint from disk and history."""
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_id}.json"
        if checkpoint_path.exists():
            checkpoint_path.unlink()

        if checkpoint_id in self.checkpoint_history:
            self.checkpoint_history.remove(checkpoint_id)
            self._save_checkpoint_index()
            logger.info(f"[ROLLBACK] Deleted checkpoint: {checkpoint_id}")
            return True
        return False

    def diff_checkpoints(self, cp_id_a: str, cp_id_b: str) -> Dict:
        """
        Compare two checkpoints and return differences.

        Returns a dictionary showing keys that differ between the two states.
        """
        cp_a = self.get_checkpoint(cp_id_a)
        cp_b = self.get_checkpoint(cp_id_b)

        if cp_a is None or cp_b is None:
            return {"error": "One or both checkpoints not found"}

        diff = {}
        all_keys = set(cp_a.data.keys()) | set(cp_b.data.keys())

        for key in all_keys:
            val_a = cp_a.data.get(key)
            val_b = cp_b.data.get(key)
            if val_a != val_b:
                diff[key] = {
                    "checkpoint_a": val_a,
                    "checkpoint_b": val_b,
                }

        return {
            "checkpoint_a": cp_id_a,
            "checkpoint_b": cp_id_b,
            "differences": diff,
            "keys_changed": list(diff.keys()),
        }

    def get_rollback_history(self, limit: int = 50) -> List[Dict]:
        """Return recent rollback events."""
        return self._rollback_log[-limit:]

    def _enforce_retention(self):
        """Remove oldest checkpoints if over the retention limit."""
        while len(self.checkpoint_history) > self.max_checkpoints:
            oldest_id = self.checkpoint_history.pop(0)
            oldest_path = self.checkpoint_dir / f"{oldest_id}.json"
            if oldest_path.exists():
                oldest_path.unlink()
            logger.debug(f"[ROLLBACK] Pruned old checkpoint: {oldest_id}")
        self._save_checkpoint_index()

    def _load_checkpoint_index(self):
        """Load checkpoint history index from disk."""
        index_path = self.checkpoint_dir / "_index.json"
        if index_path.exists():
            try:
                with index_path.open("r", encoding="utf-8") as f:
                    self.checkpoint_history = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.checkpoint_history = []

    def _save_checkpoint_index(self):
        """Persist checkpoint history index to disk."""
        index_path = self.checkpoint_dir / "_index.json"
        try:
            with index_path.open("w", encoding="utf-8") as f:
                json.dump(self.checkpoint_history, f)
        except OSError:
            logger.warning("Failed to save checkpoint index")

    def _persist_rollback_event(self, event: Dict):
        """Append rollback event to provenance log."""
        log_path = self.checkpoint_dir / "rollback_history.jsonl"
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        except OSError:
            logger.warning("Failed to persist rollback event")
