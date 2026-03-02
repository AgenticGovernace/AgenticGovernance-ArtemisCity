"""Tests for the governance monitor (src/integration/governance.py)."""

import sys
import json

sys.modules.pop("integration.governance", None)

import pytest
from pathlib import Path
from integration.governance import GovernanceMonitor


class TestGovernanceMonitor:
    @pytest.fixture
    def monitor(self, tmp_path):
        log_path = str(tmp_path / "governance" / "events.log")
        return GovernanceMonitor(alert_threshold=3, log_path=log_path)

    def test_initial_state(self, monitor):
        assert monitor.get_failure_streak() == 0
        assert monitor.get_recent_events() == []

    def test_record_failure_increments_streak(self, monitor):
        monitor.record_failure({"error": "sync divergence"})
        assert monitor.get_failure_streak() == 1

    def test_record_failure_returns_false_below_threshold(self, monitor):
        assert monitor.record_failure({"error": "e1"}) is False
        assert monitor.record_failure({"error": "e2"}) is False

    def test_record_failure_returns_true_at_threshold(self, monitor):
        monitor.record_failure({"error": "e1"})
        monitor.record_failure({"error": "e2"})
        result = monitor.record_failure({"error": "e3"})
        assert result is True

    def test_alert_event_appended(self, monitor):
        for i in range(3):
            monitor.record_failure({"error": f"e{i}"})
        events = monitor.get_recent_events()
        alert_events = [e for e in events if e.get("type") == "governance_alert"]
        assert len(alert_events) == 1
        assert alert_events[0]["failures_in_streak"] == 3

    def test_record_success_resets_streak(self, monitor):
        monitor.record_failure({"error": "e1"})
        monitor.record_failure({"error": "e2"})
        monitor.record_success()
        assert monitor.get_failure_streak() == 0

    def test_record_success_when_zero(self, monitor):
        # Should not raise
        monitor.record_success()
        assert monitor.get_failure_streak() == 0

    def test_events_have_timestamps(self, monitor):
        monitor.record_failure({"error": "e1"})
        events = monitor.get_recent_events()
        assert "timestamp" in events[0]

    def test_events_have_type(self, monitor):
        monitor.record_failure({"error": "e1"})
        events = monitor.get_recent_events()
        assert events[0]["type"] == "memory_bus_failure"

    def test_get_recent_events_limit(self, monitor):
        for i in range(10):
            monitor.record_failure({"error": f"e{i}"})
        recent = monitor.get_recent_events(limit=3)
        assert len(recent) == 3

    def test_persist_writes_jsonl(self, monitor, tmp_path):
        monitor.record_failure({"error": "disk full"})
        log_file = tmp_path / "governance" / "events.log"
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) >= 1
        data = json.loads(lines[0])
        assert data["error"] == "disk full"
        assert data["type"] == "memory_bus_failure"

    def test_persist_oserror_swallowed(self, monitor, monkeypatch):
        def _raise(*args, **kwargs):
            raise OSError("disk failure")

        monkeypatch.setattr(Path, "open", _raise)
        # Should not raise
        monitor.record_failure({"error": "e1"})
        assert monitor.get_failure_streak() == 1

    def test_original_event_not_mutated(self, monitor):
        original = {"error": "e1"}
        monitor.record_failure(original)
        assert "timestamp" not in original
        assert "type" not in original

    def test_threshold_one(self, tmp_path):
        m = GovernanceMonitor(alert_threshold=1, log_path=str(tmp_path / "e.log"))
        assert m.record_failure({"error": "x"}) is True

    def test_continued_failures_past_threshold(self, monitor):
        for i in range(5):
            monitor.record_failure({"error": f"e{i}"})
        # Every failure at or above threshold triggers alert
        assert monitor.get_failure_streak() == 5
        events = monitor.get_recent_events()
        alerts = [e for e in events if e.get("type") == "governance_alert"]
        assert len(alerts) == 3  # alerts at streak 3, 4, 5
