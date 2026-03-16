"""Integration tests for governance and rollback functionality."""

import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parents[2] / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
else:
    sys.path.remove(_src)
    sys.path.insert(0, _src)
for _key in [
    k for k in sys.modules if k == "governance" or k.startswith("governance.")
]:
    del sys.modules[_key]

import pytest
from governance.self_update_governance import (
    SelfUpdateGovernor,
    ApprovalLevel,
    WorkflowChange,
    ApprovalDecision,
    ProposalStatus,
    SandboxTestResults,
)
from governance.rollback import RollbackManager, Checkpoint

# ---------------------------------------------------------------------------
# SelfUpdateGovernor tests
# ---------------------------------------------------------------------------


class TestSelfUpdateGovernor:
    """Tests for SelfUpdateGovernor class."""

    @pytest.fixture
    def governor(self):
        """Governor with no registry — defaults to HUMAN_REQUIRED."""
        return SelfUpdateGovernor(log_dir="logs/gov_logs")

    def test_governor_initialization(self, governor):
        """Governor is created with sensible defaults."""
        assert governor.registry is None
        assert governor.sandbox_test_count == 1000
        assert governor.max_failure_rate == 0.05
        assert governor.max_perf_regression == 0.20

    def test_evaluate_proposal_sync_returns_decision(self, governor):
        """evaluate_proposal_sync returns an ApprovalDecision."""
        change = WorkflowChange(
            change_type="config_update",
            target_component="memory_bus",
            description="Increase batch size",
            proposed_diff={"batch_size": 200},
        )
        decision = governor.evaluate_proposal_sync("agent_A", change)
        assert isinstance(decision, ApprovalDecision)

    def test_no_registry_requires_human(self, governor):
        """Without a registry, every proposal requires human review."""
        change = WorkflowChange(
            change_type="config_update",
            target_component="agent_router",
            description="Tweak routing weight",
        )
        decision = governor.evaluate_proposal_sync("agent_A", change)
        assert decision.status == "pending_human_review"
        assert decision.requires_human is True
        assert decision.approval_level == ApprovalLevel.HUMAN_REQUIRED

    def test_lint_catches_missing_description(self):
        """Lint rejects proposals with empty description."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        # Provide a mock registry that gives a high trust score
        # so the proposal doesn't short-circuit to HUMAN_REQUIRED
        gov.registry = _MockRegistry(composite=0.90)

        change = WorkflowChange(
            change_type="config_update",
            target_component="memory_bus",
            description="",  # empty
        )
        decision = gov.evaluate_proposal_sync("agent_A", change)
        assert decision.status == "rejected"
        assert (
            "lint" in decision.reason.lower()
            or "description" in decision.reason.lower()
        )

    def test_lint_catches_missing_target_component(self):
        """Lint rejects proposals with empty target_component."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        gov.registry = _MockRegistry(composite=0.90)

        change = WorkflowChange(
            change_type="config_update",
            target_component="",  # empty
            description="Some change",
        )
        decision = gov.evaluate_proposal_sync("agent_A", change)
        assert decision.status == "rejected"

    def test_lint_catches_suspicious_patterns(self):
        """Lint rejects proposals with dangerous patterns like 'admin'."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        gov.registry = _MockRegistry(composite=0.90)

        change = WorkflowChange(
            change_type="config_update",
            target_component="agent_router",
            description="Escalate privileges",
            proposed_diff={"role": "admin"},
        )
        decision = gov.evaluate_proposal_sync("agent_A", change)
        assert decision.status == "rejected"
        assert (
            "suspicious" in decision.reason.lower()
            or "admin" in decision.reason.lower()
        )

    def test_auto_approve_with_high_trust(self):
        """Proposals from high-trust agents auto-approve (score > 0.85)."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        gov.registry = _MockRegistry(composite=0.90)

        change = WorkflowChange(
            change_type="routing_weight",
            target_component="hebbian_layer",
            description="Strengthen agent-task link",
            proposed_diff={"weight_delta": 0.1},
        )
        decision = gov.evaluate_proposal_sync("agent_A", change)
        assert decision.status == "approved"
        assert decision.approval_level == ApprovalLevel.AUTO_APPROVE
        assert decision.staged_rollout is False

    def test_monitored_approve_with_mid_trust(self):
        """Mid-trust agents get approved with staged rollout (0.70 < score <= 0.85)."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        gov.registry = _MockRegistry(composite=0.80)

        change = WorkflowChange(
            change_type="workflow_add",
            target_component="memory_bus",
            description="Add decay hook",
            proposed_diff={"hook": "decay_trigger"},
        )
        decision = gov.evaluate_proposal_sync("agent_B", change)
        assert decision.status == "approved"
        assert decision.approval_level == ApprovalLevel.MONITORED_APPROVE
        assert decision.staged_rollout is True

    def test_proposal_history(self, governor):
        """Proposals are logged in the governor's history."""
        change = WorkflowChange(
            change_type="config_update",
            target_component="kernel",
            description="Test history",
        )
        governor.evaluate_proposal_sync("agent_A", change)
        # evaluate_proposal_sync doesn't call _log_proposal directly,
        # but evaluate_proposal (async) does. History may be empty for sync.
        # This test just verifies no crash.
        history = governor.get_proposal_history()
        assert isinstance(history, list)

    def test_decision_to_dict(self, governor):
        """ApprovalDecision serializes to dict correctly."""
        change = WorkflowChange(
            change_type="config_update",
            target_component="kernel",
            description="Serialize test",
        )
        decision = governor.evaluate_proposal_sync("agent_A", change)
        d = decision.to_dict()
        assert "status" in d
        assert "reason" in d
        assert "requires_human" in d
        assert "timestamp" in d

    def test_multiple_proposals(self):
        """Multiple proposals can be evaluated independently."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        gov.registry = _MockRegistry(composite=0.90)

        changes = [
            WorkflowChange("config_update", "agent_router", "Change A", {"a": 1}),
            WorkflowChange("routing_weight", "hebbian_layer", "Change B", {"b": 2}),
            WorkflowChange("workflow_add", "memory_bus", "Change C", {"c": 3}),
        ]
        decisions = [gov.evaluate_proposal_sync("agent_A", c) for c in changes]
        assert all(d.status == "approved" for d in decisions)
        assert len(decisions) == 3

    @pytest.mark.asyncio
    async def test_evaluate_proposal_async_pipeline(self):
        """Async pipeline evaluates and logs proposal decisions."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        gov.registry = type(
            "Registry", (), {"scores": {"agent_A": _MockAgentScore(0.90)}}
        )()
        change = WorkflowChange(
            change_type="config_update",
            target_component="kernel",
            description="Async evaluation",
            proposed_diff={"safe": True},
        )

        decision = await gov.evaluate_proposal("agent_A", change)
        assert decision.status == "approved"
        history = gov.get_proposal_history()
        assert len(history) == 1

    def test_determine_approval_level_missing_agent_score(self):
        """Unknown agent score defaults to HUMAN_REQUIRED."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        gov.registry = type("Registry", (), {"scores": {}})()
        assert gov._determine_approval_level("unknown") == ApprovalLevel.HUMAN_REQUIRED

    def test_determine_approval_level_low_trust(self):
        """Scores <= 0.70 require human review."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        gov.registry = type(
            "Registry", (), {"scores": {"agent_low": _MockAgentScore(0.70)}}
        )()
        assert (
            gov._determine_approval_level("agent_low") == ApprovalLevel.HUMAN_REQUIRED
        )

    def test_make_decision_human_required(self, governor):
        """Decision engine escalates when trust tier is HUMAN_REQUIRED."""
        decision = governor._make_decision(
            approval_level=ApprovalLevel.HUMAN_REQUIRED,
            sandbox_results=SandboxTestResults(total_tests=10, passed=10),
            lint_issues=[],
            perf_regression=0.0,
        )
        assert decision.status == "pending_human_review"
        assert decision.requires_human is True

    def test_make_decision_rejects_on_sandbox_failures(self, governor):
        """Sandbox failure rate above threshold is rejected."""
        decision = governor._make_decision(
            approval_level=ApprovalLevel.AUTO_APPROVE,
            sandbox_results=SandboxTestResults(total_tests=10, passed=8, failed=2),
            lint_issues=[],
            perf_regression=0.0,
        )
        assert decision.status == "rejected"
        assert "sandbox failure rate" in decision.reason.lower()

    def test_make_decision_rejects_on_perf_regression(self, governor):
        """Performance regressions above threshold are rejected."""
        decision = governor._make_decision(
            approval_level=ApprovalLevel.AUTO_APPROVE,
            sandbox_results=SandboxTestResults(total_tests=10, passed=10, failed=0),
            lint_issues=[],
            perf_regression=0.25,
        )
        assert decision.status == "rejected"
        assert decision.requires_human is True

    def test_decision_to_dict_includes_sandbox_rates(self):
        """Serialized decisions include sandbox metrics when present."""
        decision = ApprovalDecision(
            status="approved",
            reason="ok",
            sandbox_results=SandboxTestResults(
                total_tests=20, passed=18, failed=1, errors=1
            ),
            approval_level=ApprovalLevel.AUTO_APPROVE,
        )
        data = decision.to_dict()
        assert data["sandbox_pass_rate"] == pytest.approx(0.9)
        assert data["sandbox_failure_rate"] == pytest.approx(0.1)

    def test_log_proposal_persist_failure_is_non_fatal(self, monkeypatch):
        """OSError while persisting proposal logs should not crash logging."""
        gov = SelfUpdateGovernor(log_dir="logs/gov")
        decision = ApprovalDecision(status="approved", reason="ok")
        change = WorkflowChange("config_update", "kernel", "desc", {"x": 1})

        original_open = Path.open

        def _open_with_failure(path_obj, *args, **kwargs):
            if path_obj.name == "proposals.jsonl":
                raise OSError("disk full")
            return original_open(path_obj, *args, **kwargs)

        monkeypatch.setattr(Path, "open", _open_with_failure)
        gov._log_proposal("agent_A", change, decision, eval_latency_ms=1.0)
        assert len(gov.get_proposal_history()) == 1


class TestSandboxTestResults:
    """Tests for SandboxTestResults dataclass."""

    def test_pass_rate(self):
        r = SandboxTestResults(total_tests=100, passed=95, failed=3, errors=2)
        assert r.pass_rate == pytest.approx(0.95)

    def test_failure_rate(self):
        r = SandboxTestResults(total_tests=100, passed=95, failed=3, errors=2)
        assert r.failure_rate == pytest.approx(0.05)

    def test_zero_tests(self):
        r = SandboxTestResults(total_tests=0)
        assert r.pass_rate == 0.0
        assert r.failure_rate == 0.0


class TestApprovalLevel:
    """Tests for ApprovalLevel enum values."""

    def test_enum_values(self):
        assert ApprovalLevel.AUTO_APPROVE.value == "auto"
        assert ApprovalLevel.MONITORED_APPROVE.value == "monitored"
        assert ApprovalLevel.HUMAN_REQUIRED.value == "human"


# ---------------------------------------------------------------------------
# RollbackManager tests
# ---------------------------------------------------------------------------


class TestRollbackManager:
    """Tests for RollbackManager class."""

    @pytest.fixture
    def manager(self, tmp_path):
        return RollbackManager(
            checkpoint_dir=str(tmp_path / "checkpoints"),
            max_checkpoints=10,
        )

    def test_manager_initialization(self, manager):
        """Manager starts with empty history."""
        assert isinstance(manager.checkpoint_history, list)
        assert len(manager.checkpoint_history) == 0

    def test_create_checkpoint_returns_id(self, manager):
        """create_checkpoint returns a string checkpoint ID."""
        cp_id = manager.create_checkpoint(
            label="v1.0",
            state={"agent_registry": {"agent_A": 0.9}},
        )
        assert isinstance(cp_id, str)
        assert "v1.0" in cp_id

    def test_checkpoint_in_history(self, manager):
        """Created checkpoints appear in checkpoint_history."""
        cp_id = manager.create_checkpoint("v1", state={"key": "val"})
        assert cp_id in manager.checkpoint_history

    def test_get_checkpoint(self, manager):
        """get_checkpoint returns a Checkpoint object."""
        cp_id = manager.create_checkpoint(
            "test_cp",
            state={"agent_registry": {"agent_A": 0.95}},
        )
        cp = manager.get_checkpoint(cp_id)
        assert cp is not None
        assert isinstance(cp, Checkpoint)
        assert cp.label == "test_cp"
        assert cp.data["agent_registry"] == {"agent_A": 0.95}

    def test_get_nonexistent_checkpoint(self, manager):
        """get_checkpoint returns None for missing checkpoint."""
        cp = manager.get_checkpoint("nonexistent_id")
        assert cp is None

    def test_rollback_to(self, manager):
        """rollback_to returns the saved state."""
        state = {
            "agent_registry": {"agent_A": 0.9},
            "kernel_config": {"batch_size": 100},
        }
        cp_id = manager.create_checkpoint("before_change", state=state)
        restored = manager.rollback_to(cp_id)
        assert restored["agent_registry"] == {"agent_A": 0.9}
        assert restored["kernel_config"] == {"batch_size": 100}

    def test_rollback_to_missing_raises(self, manager):
        """rollback_to raises FileNotFoundError for missing checkpoint."""
        with pytest.raises(FileNotFoundError):
            manager.rollback_to("does_not_exist")

    def test_list_checkpoints(self, manager):
        """list_checkpoints returns metadata for all checkpoints."""
        manager.create_checkpoint("cp1", state={"v": 1})
        manager.create_checkpoint("cp2", state={"v": 2})
        manager.create_checkpoint("cp3", state={"v": 3})
        listing = manager.list_checkpoints()
        assert len(listing) == 3
        labels = [cp["label"] for cp in listing]
        assert "cp1" in labels
        assert "cp2" in labels
        assert "cp3" in labels

    def test_get_latest_checkpoint_id(self, manager):
        """get_latest_checkpoint_id returns the most recent ID."""
        manager.create_checkpoint("first")
        last_id = manager.create_checkpoint("second")
        assert manager.get_latest_checkpoint_id() == last_id

    def test_get_latest_when_empty(self, manager):
        """get_latest_checkpoint_id returns None when empty."""
        assert manager.get_latest_checkpoint_id() is None

    def test_delete_checkpoint(self, manager):
        """delete_checkpoint removes checkpoint from history and disk."""
        cp_id = manager.create_checkpoint("to_delete", state={"x": 1})
        assert cp_id in manager.checkpoint_history

        result = manager.delete_checkpoint(cp_id)
        assert result is True
        assert cp_id not in manager.checkpoint_history
        assert manager.get_checkpoint(cp_id) is None

    def test_delete_nonexistent_returns_false(self, manager):
        """Deleting a nonexistent checkpoint returns False."""
        result = manager.delete_checkpoint("no_such_id")
        assert result is False

    def test_diff_checkpoints(self, manager):
        """diff_checkpoints shows differences between two states."""
        id_a = manager.create_checkpoint("v1", state={"agent_registry": {"a": 1}})
        id_b = manager.create_checkpoint(
            "v2", state={"agent_registry": {"a": 2, "b": 3}}
        )
        diff = manager.diff_checkpoints(id_a, id_b)
        assert "differences" in diff
        assert "agent_registry" in diff["differences"]

    def test_diff_missing_checkpoint(self, manager):
        """diff_checkpoints returns error when a checkpoint is missing."""
        id_a = manager.create_checkpoint("only_one", state={})
        diff = manager.diff_checkpoints(id_a, "nonexistent")
        assert "error" in diff

    def test_retention_policy(self, manager):
        """Retention enforcement keeps at most max_checkpoints."""
        for i in range(15):
            manager.create_checkpoint(f"cp_{i}", state={"index": i})
        assert len(manager.checkpoint_history) <= 10

    def test_rollback_history(self, manager):
        """Rollback events are recorded in history."""
        cp_id = manager.create_checkpoint("rollback_test", state={"s": "old"})
        manager.rollback_to(cp_id)
        history = manager.get_rollback_history()
        assert len(history) >= 1
        assert history[-1]["checkpoint_id"] == cp_id

    def test_checkpoint_has_timestamp(self, manager):
        """Checkpoints include a timestamp."""
        cp_id = manager.create_checkpoint("ts_test", state={})
        cp = manager.get_checkpoint(cp_id)
        assert cp.timestamp > 0

    def test_checkpoint_with_metadata(self, manager):
        """Checkpoints can store arbitrary metadata."""
        cp_id = manager.create_checkpoint(
            "meta_test",
            state={"data": 1},
            metadata={"trigger": "unit_test", "agent": "test_agent"},
        )
        cp = manager.get_checkpoint(cp_id)
        assert cp.metadata["trigger"] == "unit_test"
        assert cp.metadata["agent"] == "test_agent"

    def test_multiple_rollbacks(self, manager):
        """Multiple rollbacks are tracked independently."""
        id1 = manager.create_checkpoint("cp1", state={"v": 1})
        id2 = manager.create_checkpoint("cp2", state={"v": 2})
        manager.rollback_to(id1)
        manager.rollback_to(id2)
        history = manager.get_rollback_history()
        assert len(history) >= 2

    def test_checkpoint_to_dict(self):
        """Checkpoint serialization includes metadata and derived fields."""
        cp = Checkpoint(
            id="cp_1",
            label="v1",
            timestamp=1.0,
            data={"a": 1},
            metadata={"source": "test"},
        )
        data = cp.to_dict()
        assert data["id"] == "cp_1"
        assert data["metadata"]["source"] == "test"
        assert "created_at" in data

    def test_list_checkpoints_skips_corrupt_files(self, manager):
        """Corrupt checkpoint files are ignored safely."""
        cp_id = manager.create_checkpoint("corrupt_me", state={"x": 1})
        cp_file = Path(manager.checkpoint_dir) / f"{cp_id}.json"
        cp_file.write_text("{not-valid-json", encoding="utf-8")

        listing = manager.list_checkpoints()
        assert isinstance(listing, list)
        assert all(item["id"] != cp_id for item in listing)

    def test_load_checkpoint_index_corrupt_file(self, tmp_path):
        """Corrupt index file should result in empty history."""
        cp_dir = tmp_path / "cp_corrupt"
        cp_dir.mkdir(parents=True, exist_ok=True)
        (cp_dir / "_index.json").write_text("{bad json", encoding="utf-8")

        manager = RollbackManager(checkpoint_dir=str(cp_dir), max_checkpoints=10)
        assert manager.checkpoint_history == []

    def test_save_checkpoint_index_oserror(self, manager, monkeypatch):
        """OSError when saving index is handled without raising."""
        original_open = Path.open

        def _open_with_failure(path_obj, *args, **kwargs):
            if path_obj.name == "_index.json" and args and args[0] == "w":
                raise OSError("write blocked")
            return original_open(path_obj, *args, **kwargs)

        monkeypatch.setattr(Path, "open", _open_with_failure)
        manager._save_checkpoint_index()

    def test_persist_rollback_event_oserror(self, manager, monkeypatch):
        """Rollback event persistence failures are non-fatal."""
        original_open = Path.open

        def _open_with_failure(path_obj, *args, **kwargs):
            if path_obj.name == "rollback_history.jsonl":
                raise OSError("write blocked")
            return original_open(path_obj, *args, **kwargs)

        monkeypatch.setattr(Path, "open", _open_with_failure)
        manager._persist_rollback_event({"event": "rollback", "checkpoint_id": "cp"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockAgentScore:
    """Minimal mock for AgentScore from agent_registry."""

    def __init__(self, composite: float):
        self.composite_score = composite


class _MockRegistry:
    """Minimal mock for AgentRegistry to control trust score in tests."""

    def __init__(self, composite: float):
        self.scores = {}
        self._default_score = composite

    def __getattr__(self, name):
        if name == "scores":
            return self.__dict__.get("scores", {})
        raise AttributeError(name)

    class _Scores(dict):
        pass

    def _ensure_score(self, agent_id):
        if agent_id not in self.scores:
            self.scores[agent_id] = _MockAgentScore(self._default_score)

    def __init__(self, composite: float):
        self.scores = {}
        self._default_composite = composite

    def __getattribute__(self, name):
        if name == "scores":
            return _AutoScoreDict(object.__getattribute__(self, "_default_composite"))
        return object.__getattribute__(self, name)


class _AutoScoreDict(dict):
    """Dict that auto-creates MockAgentScore entries on access."""

    def __init__(self, composite):
        super().__init__()
        self._composite = composite

    def get(self, key, default=None):
        return _MockAgentScore(self._composite)
