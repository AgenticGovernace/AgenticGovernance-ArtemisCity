"""
Lightweight governance monitor to record memory bus failures and trigger alerts
when repeated divergence is detected.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from utils.helpers import logger


class GovernanceMonitor:
    """Tracks failures and emits alerts/rollback signals after thresholds are crossed."""

    def __init__(
        self, alert_threshold: int = 3, log_path: str = "data/governance_events.log"
    ):
        self.alert_threshold = alert_threshold
        self.log_path = Path(log_path)
        self._failure_streak = 0
        self._events: List[Dict] = []
        if self.log_path.parent:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record_failure(self, event: Dict) -> bool:
        """
        Record a failed sync/divergence event.

        Returns:
            True if alert threshold reached and rollback/inspection is advised.
        """
        self._failure_streak += 1
        event = dict(event)
        event["timestamp"] = time.time()
        event["type"] = "memory_bus_failure"
        self._events.append(event)
        self._persist_event(event)

        if self._failure_streak >= self.alert_threshold:
            alert_event = {
                "type": "governance_alert",
                "timestamp": time.time(),
                "message": "Repeated memory bus failures detected; trigger rollback/inspection.",
                "failures_in_streak": self._failure_streak,
            }
            self._events.append(alert_event)
            self._persist_event(alert_event)
            logger.error(alert_event["message"])
            return True
        return False

    def record_success(self):
        """Reset failure streak after successful operation."""
        if self._failure_streak:
            logger.info("Memory bus recovered; resetting failure streak.")
        self._failure_streak = 0

    def _persist_event(self, event: Dict):
        """Append event to governance log as JSONL."""
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        except OSError:
            logger.warning("Failed to write governance event log.")

    def get_failure_streak(self) -> int:
        return self._failure_streak

    def get_recent_events(self, limit: int = 50) -> List[Dict]:
        """Return recent events from memory; does not re-read the file."""
        return self._events[-limit:]
