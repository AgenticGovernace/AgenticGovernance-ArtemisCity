"""Integration tests for governance and rollback functionality.

Tests the approval-tier classifier (``src.governance.approvals``) and the
rollback manager (``src.governance.rollback``).
"""

import sys
from pathlib import Path

# Ensure ``src/`` is on sys.path so both ``src.governance.*`` and the
# ``utils.helpers`` import inside rollback.py resolve correctly.
_repo = str(Path(__file__).resolve().parents[3])
if _repo not in sys.path:
    sys.path.insert(0, _repo)
_src = str(Path(__file__).resolve().parents[2])
if _src not in sys.path:
    sys.path.insert(0, _src)
for _key in [k for k in sys.modules if k == "governance" or k.startswith("governance.")]:
    del sys.modules[_key]

import pytest
from src.governance.approvals import (
    SelfUpdateGovernor,
    ApprovalTier,
    UpdateProposal,
    ApprovalDecision,
)
from src.governance.rollback import RollbackManager, Checkpoint


# ---------------------------------------------------------------------------
# SelfUpdateGovernor / ApprovalTier tests
# ---------------------------------------------------------------------------

class TestApprovalTier:
    """Tests for ApprovalTier enum values."""

    def test_enum_values(self):
        assert ApprovalTier.AUTO.value == "auto"
        assert ApprovalTier.MONITORED.value == "monitored"
        assert ApprovalTier.HUMAN.value == "human"


class TestSelfUpdateGovernor:
    """Tests for SelfUpdateGovernor.classify()."""

    @pytest.fixture
    def governor(self):
        return SelfUpdateGovernor()

    def test_auto_approve_high_trust_low_risk(self, governor):
        """High trust + low risk => AUTO tier."""
        proposal = UpdateProposal(agent_name="agent_A", code_change_ratio=0.005)
        decision = governor.classify(proposal, trust_score=0.95)
        assert isinstance(decision, ApprovalDecision)
        assert decision.tier == ApprovalTier.AUTO
        assert decision.auto_approved is True
        assert decision.requires_human is False

    def test_monitored_mid_trust(self, governor):
        """Trust between 0.70 and 0.90 => MONITORED."""
        proposal = UpdateProposal(agent_name="agent_B", code_change_ratio=0.005)
        decision = governor.classify(proposal, trust_score=0.80)
        assert decision.tier == ApprovalTier.MONITORED
        assert decision.auto_approved is False
        assert decision.requires_human is False

    def test_human_low_trust(self, governor):
        """Trust < 0.70 => HUMAN."""
        proposal = UpdateProposal(agent_name="agent_C", code_change_ratio=0.005)
        decision = governor.classify(proposal, trust_score=0.50)
        assert decision.tier == ApprovalTier.HUMAN
        assert decision.requires_human is True

    def test_human_unknown_agent(self, governor):
        """has_history=False forces HUMAN regardless of trust."""
        proposal = UpdateProposal(agent_name="new_agent")
        decision = governor.classify(proposal, trust_score=0.95, has_history=False)
        assert decision.tier == ApprovalTier.HUMAN
        assert decision.requires_human is True

    def test_human_breaking_changes(self, governor):
        """Breaking changes escalate to HUMAN even with high trust."""
        proposal = UpdateProposal(
            agent_name="agent_A",
            breaking_changes=True,
        )
        decision = governor.classify(proposal, trust_score=0.95)
        assert decision.tier == ApprovalTier.HUMAN

    def test_human_policy_change(self, governor):
        """Policy changes escalate to HUMAN."""
        proposal = UpdateProposal(agent_name="agent_A", policy_change=True)
        decision = governor.classify(proposal, trust_score=0.95)
        assert decision.tier == ApprovalTier.HUMAN

    def test_human_affects_governance(self, governor):
        """Governance modifications escalate to HUMAN."""
        proposal = UpdateProposal(agent_name="agent_A", affects_governance=True)
        decision = governor.classify(proposal, trust_score=0.95)
        assert decision.tier == ApprovalTier.HUMAN

    def test_human_large_code_change(self, governor):
        """Code change > 10% escalates to HUMAN."""
        proposal = UpdateProposal(agent_name="agent_A", code_change_ratio=0.15)
        decision = governor.classify(proposal, trust_score=0.95)
        assert decision.tier == ApprovalTier.HUMAN

    def test_monitored_new_dependencies(self, governor):
        """New dependencies escalate to at least MONITORED."""
        proposal = UpdateProposal(agent_name="agent_A", new_dependencies=True)
        decision = governor.classify(proposal, trust_score=0.95)
        assert decision.tier == ApprovalTier.MONITORED

    def test_monitored_moderate_code_change(self, governor):
        """Code change between 1% and 10% => MONITORED."""
        proposal = UpdateProposal(agent_name="agent_A", code_change_ratio=0.05)
        decision = governor.classify(proposal, trust_score=0.95)
        assert decision.tier == ApprovalTier.MONITORED

    def test_decision_reasons_populated(self, governor):
        """Decisions carry human-readable reasons."""
        proposal = UpdateProposal(
            agent_name="agent_A",
            breaking_changes=True,
            policy_change=True,
        )
        decision = governor.classify(proposal, trust_score=0.95)
        assert len(decision.reasons) >= 2

    def test_decision_to_dict(self, governor):
        """ApprovalDecision.to_dict() returns expected keys."""
        proposal = UpdateProposal(agent_name="agent_A")
        decision = governor.classify(proposal, trust_score=0.95)
        d = decision.to_dict()
        assert "tier" in d
        assert "auto_approved" in d
        assert "requires_human" in d
        assert "reasons" in d

    def test_multiple_proposals_independent(self, governor):
        """Multiple proposals are classified independently."""
        proposals = [
            UpdateProposal(agent_name="a1", code_change_ratio=0.001),
            UpdateProposal(agent_name="a2", breaking_changes=True),
        ]
        decisions = [governor.classify(p, trust_score=0.95) for p in proposals]
        assert decisions[0].tier == ApprovalTier.AUTO
        assert decisions[1].tier == ApprovalTier.HUMAN


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
        id_b = manager.create_checkpoint("v2", state={"agent_registry": {"a": 2, "b": 3}})
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
