"""Tests for the TS<->Python JSON bridge (src/api_bridge.py)."""

import json
import subprocess
import sys

import pytest

from src.agents.base_agent import BaseAgent
from src.api_bridge import BridgeError, dispatch
from src.integration.agent_registry import QUARANTINE_THRESHOLD, AgentRegistry


class _StubAgent(BaseAgent):
    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success"}


@pytest.fixture
def db(tmp_path):
    """A registry DB seeded with one agent; returns its path.

    Args:
        tmp_path: Tmp path value used by this operation.

    Returns:
        None: This function does not return a value.
    """
    path = str(tmp_path / "registry.db")
    reg = AgentRegistry(db_path=path)
    reg.register_agent(_StubAgent("Alpha", capabilities=["research", "code"]))
    return path


# ---------------------------------------------------------------------------
# dispatch() — direct, in-process
# ---------------------------------------------------------------------------
class TestDispatch:
    """Provide the TestDispatch abstraction used by this module."""

    def test_list_agents(self, db):
        """Test that list agents.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch("registry.list_agents", {"db_path": db})
        assert result["total"] == 1
        agent = result["agents"][0]
        assert agent["name"] == "Alpha"
        assert agent["capabilities"] == ["research", "code"]
        assert agent["trust_tier"] == "monitored"
        assert agent["status"] == "active"

    def test_get_agent(self, db):
        """Test that get agent.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch("registry.get_agent", {"db_path": db, "name": "Alpha"})
        assert result["name"] == "Alpha"
        assert result["composite_score"] is not None

    def test_get_agent_missing(self, db):
        """Test that get agent missing.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch("registry.get_agent", {"db_path": db, "name": "ghost"})
        assert exc.value.code == "NOT_FOUND"

    def test_unknown_command(self, db):
        """Test that unknown command.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch("registry.bogus", {"db_path": db})
        assert exc.value.code == "UNKNOWN_COMMAND"

    def test_missing_required_field(self, db):
        """Test that missing required field.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch("registry.get_agent", {"db_path": db})
        assert exc.value.code == "INVALID_REQUEST"

    def test_record_and_get_violations(self, db):
        """Test that record and get violations.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "registry.record_violation",
            {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
        )
        result = dispatch("registry.get_violations", {"db_path": db, "name": "Alpha"})
        assert result["violation_count"] == 1
        assert result["quarantined"] is False
        assert len(result["violations"]) == 1

    def test_get_violations_non_integer_limit(self, db):
        """A non-integer 'limit' must surface as INVALID_REQUEST, not 500.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.get_violations",
                {"db_path": db, "name": "Alpha", "limit": "abc"},
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_get_violations_zero_limit(self, db):
        """Test that get violations zero limit.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.get_violations",
                {"db_path": db, "name": "Alpha", "limit": 0},
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_record_violation_quarantines(self, db):
        """Test that record violation quarantines.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        for _ in range(QUARANTINE_THRESHOLD):
            dispatch(
                "registry.record_violation",
                {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
            )
        result = dispatch("registry.get_violations", {"db_path": db, "name": "Alpha"})
        assert result["quarantined"] is True

    def test_clear_violations(self, db):
        """Test that clear violations.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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
        """Test that clear with invalid tier.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.clear_violations",
                {"db_path": db, "name": "Alpha", "override_tier": "god"},
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_set_trust_tier(self, db):
        """Test that set trust tier.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch(
            "registry.set_trust_tier", {"db_path": db, "name": "Alpha", "tier": "human"}
        )
        assert result["trust_tier"] == "human"

    def test_set_trust_tier_invalid(self, db):
        """Test that set trust tier invalid.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "registry.set_trust_tier",
                {"db_path": db, "name": "Alpha", "tier": "nope"},
            )
        assert exc.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# governance.* commands
# ---------------------------------------------------------------------------
class TestGovernanceCommands:
    """Provide the TestGovernanceCommands abstraction used by this module."""

    def test_compute_trust_pristine(self, db):
        """Test that compute trust pristine.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch("governance.compute_trust", {"db_path": db, "name": "Alpha"})
        # No failures / no violations -> 1.0, and it's persisted.
        assert result["trust_score"] == pytest.approx(1.0)
        assert result["persisted"] is True
        assert "components" in result["breakdown"]

    def test_compute_trust_pulls_violation_count(self, db):
        # Record one violation, then compute without passing the count.
        """Test that compute trust pulls violation count.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "registry.record_violation",
            {"db_path": db, "name": "Alpha", "violation_type": "rate_limit"},
        )
        result = dispatch(
            "governance.compute_trust",
            {"db_path": db, "name": "Alpha", "metrics": {}},
        )
        # security_score = 1 - 0.1*1 = 0.9 -> trust < 1.0
        assert result["trust_score"] < 1.0
        assert result["breakdown"]["components"]["security_score"] == pytest.approx(0.9)

    def test_compute_trust_persists_to_registry(self, db):
        """Test that compute trust persists to registry.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "governance.compute_trust",
            {
                "db_path": db,
                "name": "Alpha",
                "metrics": {"successful_executions": 5, "total_executions": 10},
            },
        )
        record = dispatch("registry.get_agent", {"db_path": db, "name": "Alpha"})
        assert record["trust_score"] is not None

    def test_compute_trust_no_persist(self, db):
        """Test that compute trust no persist.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "governance.compute_trust",
            {"db_path": db, "name": "Alpha", "persist": False},
        )
        record = dispatch("registry.get_agent", {"db_path": db, "name": "Alpha"})
        assert record["trust_score"] is None

    def test_compute_trust_unknown_agent(self, db):
        """Test that compute trust unknown agent.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch("governance.compute_trust", {"db_path": db, "name": "ghost"})
        assert exc.value.code == "NOT_FOUND"

    def test_evaluate_update_auto(self, db):
        """Test that evaluate update auto.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch(
            "governance.evaluate_update",
            {
                "db_path": db,
                "agent_name": "Alpha",
                "trust_score": 0.95,
                "code_change_ratio": 0.005,
            },
        )
        assert result["tier"] == "auto"
        assert result["auto_approved"] is True
        assert result["trust_score"] == 0.95

    def test_evaluate_update_human_on_breaking(self, db):
        """Test that evaluate update human on breaking.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch(
            "governance.evaluate_update",
            {
                "db_path": db,
                "agent_name": "Alpha",
                "trust_score": 0.99,
                "breaking_changes": True,
            },
        )
        assert result["tier"] == "human"
        assert result["requires_human"] is True

    def test_evaluate_update_from_metrics(self, db):
        """Test that evaluate update from metrics.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        result = dispatch(
            "governance.evaluate_update",
            {
                "db_path": db,
                "agent_name": "Alpha",
                "metrics": {"successful_executions": 10, "total_executions": 10},
                "code_change_ratio": 0.0,
            },
        )
        # pristine metrics -> trust 1.0 -> auto
        assert result["tier"] == "auto"

    def test_evaluate_update_uses_persisted_trust(self, db):
        # Persist a low trust score, then evaluate with no trust/metrics.
        """Test that evaluate update uses persisted trust.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        dispatch(
            "governance.compute_trust",
            {
                "db_path": db,
                "name": "Alpha",
                "metrics": {
                    "successful_executions": 1,
                    "total_executions": 10,
                    "recent_violation_count": 5,
                },
            },
        )
        result = dispatch(
            "governance.evaluate_update", {"db_path": db, "agent_name": "Alpha"}
        )
        # Low persisted trust -> human tier
        assert result["tier"] == "human"

    def test_evaluate_update_no_trust_no_metrics_errors(self, db):
        """Test that evaluate update no trust no metrics errors.

        Args:
            db: Db value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "governance.evaluate_update", {"db_path": db, "agent_name": "Alpha"}
            )
        # Alpha has no persisted trust_score yet.
        assert exc.value.code == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# CLI round-trip — exercises the stdin/stdout envelope the TS layer uses
# ---------------------------------------------------------------------------
class TestCLI:
    """Provide the TestCLI abstraction used by this module."""

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
        """Test that cli success.

        Args:
            db: Db value used by this operation.
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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
        """Test that cli error envelope.

        Args:
            db: Db value used by this operation.
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
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
        """Test that cli missing command.

        Args:
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parents[2]
        proc = self._run({"payload": {}}, cwd=str(repo_root))
        assert proc.returncode == 1
        envelope = json.loads(proc.stdout)
        assert envelope["code"] == "INVALID_REQUEST"
