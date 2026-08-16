"""Focused round-trip coverage for registry learning and trust persistence."""

from __future__ import annotations

import copy

import pytest

from src.agents.base_agent import BaseAgent
from src.integration.agent_registry import AgentRegistry
from src.integration.trust_interface import (TrustInterface, TrustLevel,
                                             TrustStore, _default_db_path)


class _StubAgent(BaseAgent):
    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success", "summary": "stub"}


def test_learning_snapshot_updates_all_mirrored_fields_without_execution(tmp_path):
    registry = AgentRegistry(db_path=str(tmp_path / "registry.db"))
    registry.register_agent(_StubAgent("Alpha", capabilities=["research"]))
    learning = {
        "weight": 0.73,
        "delta": -0.12,
        "activation_count": 12,
        "success_rate": 0.75,
        "task_type": "atp:summarize:text_summarization",
        "pair_bonus": 0.2,
        "timing_score": 0.91,
        "routing_intelligence": 0.66,
        "oscillation_rate": 0.25,
        "sentinel_alert": True,
        "sentinel_samples": 11,
    }

    registry.update_learning_snapshot("Alpha", learning)

    record = registry.store.get_agent_record("Alpha")
    assert record is not None
    assert record["hebbian_weight"] == pytest.approx(0.73)
    assert record["hebbian_delta"] == pytest.approx(-0.12)
    assert record["hebbian_activations"] == 12
    assert record["hebbian_success_rate"] == pytest.approx(0.75)
    assert record["hebbian_task_type"] == "atp:summarize:text_summarization"
    assert record["hebbian_pair_bonus"] == pytest.approx(0.2)
    assert record["hebbian_timing_score"] == pytest.approx(0.91)
    assert record["routing_intelligence"] == pytest.approx(0.66)
    assert record["hebbian_oscillation_rate"] == pytest.approx(0.25)
    assert record["hebbian_sentinel_alert"] is True
    assert record["hebbian_sentinel_samples"] == 11
    assert record["learning_updated_at"]
    assert record["execution_count"] == 0


def test_learning_snapshot_rejects_unknown_agent(tmp_path):
    registry = AgentRegistry(db_path=str(tmp_path / "registry.db"))

    with pytest.raises(ValueError, match="Unknown agent: 'missing'"):
        registry.update_learning_snapshot("missing", {"weight": 0.5})


def test_registry_snapshot_round_trip_restores_learning_and_governance(tmp_path):
    registry = AgentRegistry(db_path=str(tmp_path / "registry.db"))
    registry.register_agent(_StubAgent("Alpha", capabilities=["research"]))
    registry.update_learning_snapshot("Alpha", {"weight": 0.8, "delta": 0.1})
    registry.record_violation("Alpha", "rate_limit", {"limit": 10})
    snapshot = registry.export_snapshot()
    snapshot_agent = snapshot["agents"][0]

    registry.update_learning_snapshot("Alpha", {"weight": 0.1, "delta": -0.7})
    registry.clear_violations("Alpha", "temporary mutation")
    registry.set_trust_score("Alpha", 0.99)

    restored = registry.restore_snapshot(snapshot)

    assert restored == {"agents": 1, "violations": 1}
    record = registry.store.get_agent_record("Alpha")
    assert record is not None
    assert record["hebbian_weight"] == pytest.approx(0.8)
    assert record["hebbian_delta"] == pytest.approx(0.1)
    assert record["violation_count"] == 1
    assert record["trust_score"] == pytest.approx(snapshot_agent["trust_score"])
    assert registry.get_governance_state("Alpha") == {
        "trust_tier": "monitored",
        "status": "active",
        "violation_count": 1,
        "quarantined_at": None,
        "trust_score": pytest.approx(snapshot_agent["trust_score"]),
    }
    violations = registry.get_violations("Alpha")
    assert len(violations) == 1
    assert violations[0]["cleared"] is False


def test_registry_snapshot_restores_legacy_partial_agent_defaults(tmp_path):
    registry = AgentRegistry(db_path=str(tmp_path / "registry.db"))
    snapshot = {
        "schema_version": 1,
        "agents": [{"name": "Legacy", "capabilities": '["research"]'}],
        "violations": [],
    }

    assert registry.restore_snapshot(snapshot) == {"agents": 1, "violations": 0}

    record = registry.store.get_agent_record("Legacy")
    assert record is not None
    assert record["capabilities"] == ["research"]
    assert record["trust_tier"] == "monitored"
    assert record["status"] == "active"
    assert record["violation_count"] == 0
    assert record["hebbian_delta"] == 0.0


@pytest.mark.parametrize(
    "invalid_snapshot",
    [
        None,
        {},
        {"agents": ["not-an-object"], "violations": []},
        {"agents": [{"unknown_column": "value"}], "violations": []},
        {"agents": [{}], "violations": []},
    ],
)
def test_registry_snapshot_rejects_invalid_input_atomically(tmp_path, invalid_snapshot):
    registry = AgentRegistry(db_path=str(tmp_path / "registry.db"))
    registry.register_agent(_StubAgent("Alpha", capabilities=["research"]))
    before = copy.deepcopy(registry.export_snapshot())

    with pytest.raises(ValueError):
        registry.restore_snapshot(invalid_snapshot)

    assert registry.export_snapshot() == before


def test_default_trust_db_path_honors_environment(monkeypatch, tmp_path):
    expected = tmp_path / "custom-trust.db"
    monkeypatch.setenv("ARTEMIS_TRUST_DB", str(expected))

    assert _default_db_path() == expected.resolve()
    assert TrustStore().db_path == expected.resolve()


def test_computed_outcomes_clamp_count_and_persist(tmp_path):
    db_path = tmp_path / "trust.db"
    interface = TrustInterface(db_path=db_path)

    assert interface.record_computed_outcome("Alpha", 1.7, success=True) == 1.0
    assert interface.record_computed_outcome("Alpha", -0.4, success=False) == 0.0

    reloaded = TrustInterface(db_path=db_path)
    score = reloaded.get_trust_score("Alpha")
    assert score.score == 0.0
    assert score.level is TrustLevel.UNTRUSTED
    assert score.reinforcement_events == 1
    assert score.penalty_events == 1


def test_invalid_computed_outcome_has_no_persistent_side_effect(tmp_path):
    db_path = tmp_path / "trust.db"
    interface = TrustInterface(db_path=db_path)

    with pytest.raises(ValueError):
        interface.record_computed_outcome("invalid-agent", "not-a-score", success=True)
    with pytest.raises(ValueError):
        interface.set_authoritative_score("invalid-live-agent", "not-a-score")

    reloaded = TrustInterface(db_path=db_path)
    assert "agent:invalid-agent" not in reloaded.trust_scores
    assert "agent:invalid-live-agent" not in reloaded.trust_scores
