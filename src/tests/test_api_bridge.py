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


@pytest.fixture
def repo_root():
    import pathlib

    return pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def vault(tmp_path):
    path = tmp_path / "vault"
    path.mkdir()
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
# ATP and memory bridge commands
# ---------------------------------------------------------------------------
class TestATPCommands:
    def test_parse_atp_message_uses_canonical_values(self):
        message = """
        #Mode: Build
        #Context: Create bridge tests
        #Priority: Normal
        #Action: Execute
        #TargetZone: src/tests
        """

        result = dispatch("atp.parse", {"message": message})

        parsed = result["message"]
        assert parsed["mode"] == "Build"
        assert parsed["priority"] == "Normal"
        assert parsed["action_type"] == "Execute"
        assert result["metrics"]["has_headers"] is True

    def test_validate_malformed_atp_returns_validation_errors(self):
        result = dispatch(
            "atp.validate",
            {"message": "plain text without ATP headers", "strict": True},
        )

        validation = result["validation"]
        assert validation["is_valid"] is False
        assert any("ATP headers" in error for error in validation["errors"])

    def test_parse_atp_missing_message(self):
        with pytest.raises(BridgeError) as exc:
            dispatch("atp.parse", {})
        assert exc.value.code == "INVALID_REQUEST"


class TestMemoryCommands:
    def test_write_read_list_and_search(self, vault, tmp_path):
        payload = {
            "vault_path": str(vault),
            "vector_db_path": str(tmp_path / "vector.db"),
            "path": "notes/mars.md",
            "content": "mars mission overview",
            "metadata": {"source": "test"},
        }

        write_result = dispatch("memory.write", payload)
        assert write_result["status"] == "success"
        assert write_result["path"] == "notes/mars.md"
        assert (vault / "notes" / "mars.md").read_text() == "mars mission overview"

        read_result = dispatch(
            "memory.read",
            {"vault_path": str(vault), "path": "notes/mars.md"},
        )
        assert read_result["status"] == "success"
        assert read_result["content"] == "mars mission overview"

        list_result = dispatch(
            "memory.list",
            {"vault_path": str(vault), "path": "notes"},
        )
        assert list_result == {"path": "notes", "files": ["mars.md"], "count": 1}

        search_result = dispatch(
            "memory.search",
            {
                "vault_path": str(vault),
                "vector_db_path": str(tmp_path / "vector.db"),
                "query": "mars",
                "limit": 5,
            },
        )
        assert search_result["count"] >= 1
        assert search_result["results"][0]["path"] == "notes/mars.md"

    def test_memory_read_missing_note(self, vault):
        with pytest.raises(BridgeError) as exc:
            dispatch("memory.read", {"vault_path": str(vault), "path": "missing.md"})
        assert exc.value.code == "NOT_FOUND"

    def test_memory_write_missing_fields(self, vault):
        with pytest.raises(BridgeError) as exc:
            dispatch("memory.write", {"vault_path": str(vault), "content": "x"})
        assert exc.value.code == "INVALID_REQUEST"

    def test_memory_write_rejects_traversal(self, vault):
        with pytest.raises(BridgeError) as exc:
            dispatch(
                "memory.write",
                {
                    "vault_path": str(vault),
                    "path": "../escape.md",
                    "content": "blocked",
                },
            )
        assert exc.value.code == "INVALID_REQUEST"

    def test_memory_stats_and_delete(self, vault, tmp_path):
        base_payload = {
            "vault_path": str(vault),
            "vector_db_path": str(tmp_path / "vector.db"),
        }
        dispatch(
            "memory.write",
            {
                **base_payload,
                "path": "notes/delete-me.md",
                "content": "delete me #cleanup",
            },
        )

        stats = dispatch("memory.stats", base_payload)
        assert stats["note_count"] == 1
        assert stats["vector_count"] == 1

        deleted = dispatch(
            "memory.delete", {**base_payload, "path": "notes/delete-me.md"}
        )
        assert deleted["deleted"] is True
        assert not (vault / "notes" / "delete-me.md").exists()


class TestAgentMutationCommands:
    def test_register_update_suspend_activate_and_delete_agent(self, tmp_path):
        db_path = str(tmp_path / "registry.db")

        created = dispatch(
            "registry.register_agent",
            {
                "db_path": db_path,
                "name": "Bridge Agent",
                "capabilities": ["llm_chat", "planning"],
                "description": "Created by bridge",
                "trust_score": 0.7,
            },
        )
        assert created["name"] == "Bridge Agent"
        assert created["capabilities"] == ["llm_chat", "planning"]

        updated = dispatch(
            "registry.update_agent",
            {
                "db_path": db_path,
                "name": "Bridge Agent",
                "updates": {"capabilities": ["reasoning"], "status": "active"},
            },
        )
        assert updated["capabilities"] == ["reasoning"]

        suspended = dispatch(
            "registry.set_agent_status",
            {"db_path": db_path, "name": "Bridge Agent", "status": "suspended"},
        )
        assert suspended["status"] == "suspended"

        activated = dispatch(
            "registry.set_agent_status",
            {"db_path": db_path, "name": "Bridge Agent", "status": "active"},
        )
        assert activated["status"] == "active"

        deleted = dispatch(
            "registry.delete_agent", {"db_path": db_path, "name": "Bridge Agent"}
        )
        assert deleted == {"name": "Bridge Agent", "deleted": True}


class TestATPBackedCommands:
    def test_atp_queue_history_route_and_metadata(self, tmp_path, db):
        atp_db = str(tmp_path / "atp.db")
        message = (
            "#Mode: Build\n#Context: Create route\n#Priority: Normal\n"
            "#Action: Execute\nBuild the bridge."
        )

        sent = dispatch("atp.send", {"atp_db_path": atp_db, "message": message})
        assert sent["status"] == "queued"
        message_id = sent["message_id"]

        queued = dispatch("atp.queue", {"atp_db_path": atp_db})
        assert queued["total"] == 1
        assert queued["messages"][0]["message_id"] == message_id

        route = dispatch(
            "atp.route",
            {
                "atp_db_path": atp_db,
                "db_path": db,
                "message_id": message_id,
                "required_capability": "research",
            },
        )
        assert route["route"]["agent_name"] == "Alpha"

        stored = dispatch(
            "atp.get_message", {"atp_db_path": atp_db, "message_id": message_id}
        )
        assert stored["status"] == "routed"
        assert stored["route"]["agent_name"] == "Alpha"

        assert "Build" in dispatch("atp.modes", {})["modes"]
        assert "Normal" in dispatch("atp.priorities", {})["priorities"]
        assert "Execute" in dispatch("atp.action_types", {})["action_types"]
        assert "#Mode:" in dispatch("atp.template", {})["template"]
        formatted = dispatch(
            "atp.format",
            {
                "mode": "Review",
                "context": "Check docs",
                "action_type": "Summarize",
                "content": "Review the bridge docs.",
            },
        )
        assert formatted["parsed"]["mode"] == "Review"


class TestTrustAndHebbianCommands:
    def test_trust_score_permissions_and_events(self, tmp_path):
        trust_db = str(tmp_path / "trust.db")
        payload = {"trust_db_path": trust_db, "entity_id": "alpha"}

        score = dispatch("trust.get_score", payload)
        assert score["entity_id"] == "alpha"
        assert score["level"] == "high"

        updated = dispatch("trust.set_score", {**payload, "score": 0.95})
        assert updated["level"] == "full"

        success = dispatch("trust.record_success", {**payload, "amount": 0.01})
        assert success["recorded"] == "success"

        permissions = dispatch("trust.permissions", payload)
        assert "read" in permissions["permissions"]

        allowed = dispatch("trust.can_perform", {**payload, "operation": "read"})
        assert allowed["allowed"] is True

        report = dispatch("trust.report", {"trust_db_path": trust_db})
        assert report["total_entities"] >= 1

    def test_hebbian_weight_read_and_update(self, tmp_path):
        hebbian_db = str(tmp_path / "hebbian.db")
        updated = dispatch(
            "hebbian.update",
            {
                "hebbian_db_path": hebbian_db,
                "agent1": "Alpha",
                "agent2": "task:research",
                "delta": 2,
            },
        )
        assert updated["weight"] == 2

        weights = dispatch("hebbian.weights", {"hebbian_db_path": hebbian_db})
        assert weights["summary"]["total_connections"] == 1
        assert weights["connections"][0]["origin_node"] == "Alpha"


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

    def test_cli_success(self, db, repo_root):
        """Test that cli success.

        Args:
            db: Db value used by this operation.
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        proc = self._run(
            {"command": "registry.list_agents", "payload": {"db_path": db}},
            cwd=str(repo_root),
        )
        assert proc.returncode == 0
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is True
        assert envelope["data"]["total"] == 1

    def test_cli_error_envelope(self, db, repo_root):
        """Test that cli error envelope.

        Args:
            db: Db value used by this operation.
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        proc = self._run(
            {"command": "registry.get_agent", "payload": {"db_path": db, "name": "x"}},
            cwd=str(repo_root),
        )
        assert proc.returncode == 1
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is False
        assert envelope["code"] == "NOT_FOUND"

    def test_cli_missing_command(self, repo_root):
        """Test that cli missing command.

        Args:
            tmp_path: Tmp path value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        proc = self._run({"payload": {}}, cwd=str(repo_root))
        assert proc.returncode == 1
        envelope = json.loads(proc.stdout)
        assert envelope["code"] == "INVALID_REQUEST"

    def test_cli_atp_parse_success(self, repo_root):
        proc = self._run(
            {
                "command": "atp.parse",
                "payload": {
                    "message": "#Mode: Build\n#Priority: Normal\n#Action: Execute"
                },
            },
            cwd=str(repo_root),
        )
        assert proc.returncode == 0
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is True
        assert envelope["data"]["message"]["mode"] == "Build"
        assert envelope["data"]["message"]["priority"] == "Normal"
        assert envelope["data"]["message"]["action_type"] == "Execute"

    def test_cli_memory_write_traversal_error(self, repo_root, vault):
        proc = self._run(
            {
                "command": "memory.write",
                "payload": {
                    "vault_path": str(vault),
                    "path": "../escape.md",
                    "content": "blocked",
                },
            },
            cwd=str(repo_root),
        )
        assert proc.returncode == 1
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is False
        assert envelope["code"] == "INVALID_REQUEST"
