"""Tests for the trust interface (src/integration/trust_interface.py)."""

import sys

sys.modules.pop("integration.trust_interface", None)

import pytest
from datetime import datetime, timedelta
from integration.trust_interface import (
    TrustInterface,
    TrustLevel,
    TrustScore,
    get_trust_interface,
)


# ---------------------------------------------------------------------------
# TrustLevel enum
# ---------------------------------------------------------------------------
class TestTrustLevel:
    def test_values(self):
        assert TrustLevel.FULL.value == "full"
        assert TrustLevel.HIGH.value == "high"
        assert TrustLevel.MEDIUM.value == "medium"
        assert TrustLevel.LOW.value == "low"
        assert TrustLevel.UNTRUSTED.value == "untrusted"


# ---------------------------------------------------------------------------
# TrustScore dataclass
# ---------------------------------------------------------------------------
class TestTrustScore:
    @pytest.fixture
    def score(self):
        return TrustScore(
            entity_id="agent_1",
            entity_type="agent",
            score=0.8,
            level=TrustLevel.HIGH,
            last_updated=datetime.now(),
        )

    def test_defaults(self, score):
        assert score.decay_rate == 0.01
        assert score.reinforcement_events == 0
        assert score.penalty_events == 0

    def test_apply_decay_no_time_elapsed(self, score):
        # Same day → 0 days elapsed → no decay
        result = score.apply_decay()
        assert result == score.score

    def test_apply_decay_after_days(self):
        ts = TrustScore(
            entity_id="x",
            entity_type="agent",
            score=0.8,
            level=TrustLevel.HIGH,
            last_updated=datetime.now() - timedelta(days=10),
            decay_rate=0.01,
        )
        decayed = ts.apply_decay()
        expected = 0.8 * (0.99 ** 10)
        assert abs(decayed - expected) < 0.001

    def test_decay_respects_min_floor(self):
        ts = TrustScore(
            entity_id="x",
            entity_type="agent",
            score=0.8,
            level=TrustLevel.HIGH,
            last_updated=datetime.now() - timedelta(days=10000),
            decay_rate=0.5,
        )
        decayed = ts.apply_decay()
        # HIGH floor is 0.7
        assert decayed >= 0.7

    def test_reinforce(self, score):
        old = score.score
        new = score.reinforce(0.1)
        assert new == old + 0.1
        assert score.reinforcement_events == 1

    def test_reinforce_caps_at_one(self):
        ts = TrustScore(
            entity_id="x", entity_type="agent", score=0.95,
            level=TrustLevel.FULL, last_updated=datetime.now(),
        )
        result = ts.reinforce(0.1)
        assert result == 1.0

    def test_penalize(self, score):
        old = score.score
        new = score.penalize(0.1)
        assert new == old - 0.1
        assert score.penalty_events == 1

    def test_penalize_floors_at_zero(self):
        ts = TrustScore(
            entity_id="x", entity_type="agent", score=0.05,
            level=TrustLevel.UNTRUSTED, last_updated=datetime.now(),
        )
        result = ts.penalize(0.2)
        assert result == 0.0

    def test_update_level_transitions(self):
        ts = TrustScore(
            entity_id="x", entity_type="agent", score=0.95,
            level=TrustLevel.FULL, last_updated=datetime.now(),
        )
        # FULL
        ts._update_level()
        assert ts.level == TrustLevel.FULL

        ts.score = 0.75
        ts._update_level()
        assert ts.level == TrustLevel.HIGH

        ts.score = 0.55
        ts._update_level()
        assert ts.level == TrustLevel.MEDIUM

        ts.score = 0.35
        ts._update_level()
        assert ts.level == TrustLevel.LOW

        ts.score = 0.1
        ts._update_level()
        assert ts.level == TrustLevel.UNTRUSTED


# ---------------------------------------------------------------------------
# TrustInterface
# ---------------------------------------------------------------------------
class TestTrustInterface:
    @pytest.fixture
    def iface(self):
        return TrustInterface()

    def test_default_agents_initialized(self, iface):
        assert "artemis" in iface.trust_scores
        assert "pack_rat" in iface.trust_scores

    def test_get_trust_score_existing(self, iface):
        # Default agents are stored by plain name, but get_trust_score
        # uses "type:id" keys for NEW lookups.  The "artemis" key was
        # seeded directly in _initialize_default_agents.
        assert "artemis" in iface.trust_scores
        ts = iface.trust_scores["artemis"]
        assert ts.score >= 0.9

    def test_get_trust_score_new_agent(self, iface):
        ts = iface.get_trust_score("new_agent")
        assert ts.entity_id == "new_agent"
        assert ts.score == iface.DEFAULT_AGENT_TRUST

    def test_get_trust_score_new_memory(self, iface):
        ts = iface.get_trust_score("mem_1", entity_type="memory")
        assert ts.score == iface.DEFAULT_MEMORY_TRUST

    def test_can_perform_operation_allowed(self, iface):
        # Use a new agent created via get_trust_score (keyed correctly)
        ts = iface.get_trust_score("high_agent")
        ts.score = 0.95
        ts._update_level()
        assert iface.can_perform_operation("high_agent", "delete") is True

    def test_can_perform_operation_denied(self, iface):
        # Force low trust
        key = "agent:low_agent"
        iface.trust_scores[key] = TrustScore(
            entity_id="low_agent", entity_type="agent",
            score=0.35, level=TrustLevel.LOW, last_updated=datetime.now(),
        )
        assert iface.can_perform_operation("low_agent", "read") is True
        assert iface.can_perform_operation("low_agent", "write") is False
        assert iface.can_perform_operation("low_agent", "delete") is False

    def test_untrusted_no_operations(self, iface):
        key = "agent:bad"
        iface.trust_scores[key] = TrustScore(
            entity_id="bad", entity_type="agent",
            score=0.1, level=TrustLevel.UNTRUSTED, last_updated=datetime.now(),
        )
        assert iface.can_perform_operation("bad", "read") is False

    def test_record_success(self, iface):
        ts_before = iface.get_trust_score("planner")
        score_before = ts_before.score
        iface.record_success("planner", amount=0.05)
        ts_after = iface.get_trust_score("planner")
        assert ts_after.score > score_before

    def test_record_failure(self, iface):
        ts_before = iface.get_trust_score("planner")
        score_before = ts_before.score
        iface.record_failure("planner", amount=0.1)
        ts_after = iface.get_trust_score("planner")
        assert ts_after.score < score_before

    def test_get_trust_report(self, iface):
        report = iface.get_trust_report()
        assert "total_entities" in report
        assert report["total_entities"] >= 4
        assert "by_level" in report
        assert "timestamp" in report

    def test_filter_by_trust(self, iface):
        items = [
            {"entity_id": "artemis", "entity_type": "agent"},
            {"entity_id": "unknown_low", "entity_type": "agent"},
        ]
        # Force unknown_low to be untrusted
        key = "agent:unknown_low"
        iface.trust_scores[key] = TrustScore(
            entity_id="unknown_low", entity_type="agent",
            score=0.1, level=TrustLevel.UNTRUSTED, last_updated=datetime.now(),
        )
        filtered = iface.filter_by_trust(items, TrustLevel.HIGH)
        assert len(filtered) == 1
        assert filtered[0]["entity_id"] == "artemis"

    def test_filter_by_trust_no_entity_id(self, iface):
        items = [{"name": "no_id"}]
        filtered = iface.filter_by_trust(items)
        assert filtered == []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
class TestGetTrustInterface:
    def test_singleton(self):
        import integration.trust_interface as mod
        mod._global_trust_interface = None
        i1 = get_trust_interface()
        i2 = get_trust_interface()
        assert i1 is i2
        mod._global_trust_interface = None
