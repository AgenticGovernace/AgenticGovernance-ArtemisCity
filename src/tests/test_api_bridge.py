"""Tests for the TS<->Python JSON bridge (src/api_bridge.py)."""

import json
import subprocess
import sys

import pytest
from src.agents.base_agent import BaseAgent
from src.api_bridge import BridgeError, dispatch
from src.integration.agent_registry import AgentRegistry, QUARANTINE_THRESHOLD


class _StubAgent(BaseAgent):
    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success"}


@pytest.fixture
def db(tmp_path):
    """A registry DB seeded with one agent; returns its path."""
    path = str(tmp_path / "registry.db")
    reg = AgentRegistry(db_path=path)
    reg.register_agent(_StubAgent("Alpha", capabilities=["research", "code"]))
    return path


# ---------------------------------------------------------------------------
# dispatch() — direct, in-process
# ---------------------------------------------------------------------------
class TestDispatch:
    def test_list_agents(self, db):
        result = dispatch("registry.list_agents", {"db_path": db})
        assert result["total"] == 1
        agent = result["agents"][0]
        assert agent["name"] == "Alpha"
        assert agent["capabilities"] == ["research", "code"]
        assert agent["trust_tier"] == "monitored"
        assert agent["status"] == "active"

    def test_get_agent(self, db):
        result = dispatch("registry.get_agent", {"db_path": db, "name": "Alpha"})
        assert result["name"] == "Alpha"
        assert result["composite_score"] is not None

    def test_get_agent_missing(self, db):
        with pytest.raises(BridgeError) as exc:
            dispatch("registry.get_agent", {"db_path": db, "name": "ghost"})
        assert exc.value.code == "NOT_FOUND"

    def test_unknown_command(self, db):
        with pytest.raises(BridgeError) as exc:
            dispatch("registry.bogus", {"db_path": db})
        assert exc.value.code == "UNKNOWN_COMMAND"

    def test_missing_required_field(self, db):
        with pytest.raises(BridgeError) as exc:
            dispatch("registry.get_agent", {"db_path": db})
        assert exc.value.code == "INVALID_REQUEST"

    def test_record_and_get_violations(self, db):
        dispatch(
            "registry.record_violation",
            {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
        )
        result = dispatch("registry.get_violations", {"db_path": db, "name": "Alpha"})
        assert result["violation_count"] == 1
        assert result["quarantined"] is False
        assert len(result["violations"]) == 1

    def test_get_violations_non_integer_limit(self, db):
        """A non-integer 'limit' must surface as INVALID_REQUEST, not 500."""
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.get_violations",
                {"db_path": db, "name": "Alpha", "limit": "abc"},
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_get_violations_zero_limit(self, db):
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.get_violations",
                {"db_path": db, "name": "Alpha", "limit": 0},
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_record_violation_quarantines(self, db):
        for _ in range(QUARANTINE_THRESHOLD):
            dispatch(
                "registry.record_violation",
                {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
            )
        result = dispatch("registry.get_violations", {"db_path": db, "name": "Alpha"})
        assert result["quarantined"] is True

    def test_clear_violations(self, db):
        for _ in range(QUARANTINE_THRESHOLD):
            dispatch(
                "registry.record_violation",
                {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
            )
        result = dispatch(
            "registry.clear_violations",
            {"db_path": db, "name": "Alpha", "rationale": "reviewed"},
        )
        assert result["cleared"] == QUARANTINE_THRESHOLD
        assert result["quarantined"] is False
        assert result["violation_count"] == 0

    def test_clear_with_invalid_tier(self, db):
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.clear_violations",
                {"db_path": db, "name": "Alpha", "override_tier": "god"},
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_set_trust_tier(self, db):
        result = dispatch(
            "registry.set_trust_tier", {"db_path": db, "name": "Alpha", "tier": "human"}
        )
        assert result["trust_tier"] == "human"

    def test_set_trust_tier_invalid(self, db):
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.set_trust_tier",
                {"db_path": db, "name": "Alpha", "tier": "nope"},
            )
        assert exc.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# CLI round-trip — exercises the stdin/stdout envelope the TS layer uses
# ---------------------------------------------------------------------------
class TestCLI:
    def _run(self, request: dict, cwd):
        proc = subprocess.run(
            [sys.executable, "-m", "src.api_bridge"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        return proc

    def test_cli_success(self, db, tmp_path):
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parents[2]
        proc = self._run(
            {"command": "registry.list_agents", "payload": {"db_path": db}},
            cwd=str(repo_root),
        )
        assert proc.returncode == 0
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is True
        assert envelope["data"]["total"] == 1

    def test_cli_error_envelope(self, db, tmp_path):
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parents[2]
        proc = self._run(
            {"command": "registry.get_agent", "payload": {"db_path": db, "name": "x"}},
            cwd=str(repo_root),
        )
        assert proc.returncode == 1
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is False
        assert envelope["code"] == "NOT_FOUND"

    def test_cli_missing_command(self, tmp_path):
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parents[2]
        proc = self._run({"payload": {}}, cwd=str(repo_root))
        assert proc.returncode == 1
        envelope = json.loads(proc.stdout)
        assert envelope["code"] == "INVALID_REQUEST"
