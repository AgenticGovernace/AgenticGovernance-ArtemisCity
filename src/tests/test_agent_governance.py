"""Tests for governance data model on the agent registry.

Covers violation logging, auto-quarantine on the 3rd strike, clearing /
override, trust tier + trust score, governance column migration, and the
exclusion of blocked agents from routing.
"""

import sqlite3

import pytest
from src.agents.base_agent import BaseAgent
from src.integration.agent_registry import (
    AgentRegistry,
    AgentScore,
    QUARANTINE_THRESHOLD,
)


class _StubAgent(BaseAgent):
    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success", "summary": "stub"}


@pytest.fixture
def registry(tmp_path):
    return AgentRegistry(db_path=str(tmp_path / "registry.db"))


@pytest.fixture
def alpha(registry):
    agent = _StubAgent("Alpha", capabilities=["research"])
    registry.register_agent(agent)
    return agent


# ---------------------------------------------------------------------------
# Defaults on registration
# ---------------------------------------------------------------------------
class TestGovernanceDefaults:
    def test_new_agent_defaults(self, registry, alpha):
        state = registry.get_governance_state("Alpha")
        assert state["trust_tier"] == "monitored"
        assert state["status"] == "active"
        assert state["violation_count"] == 0
        assert state["quarantined_at"] is None

    def test_unknown_agent_state_is_none(self, registry):
        assert registry.get_governance_state("ghost") is None

    def test_not_blocked_by_default(self, registry, alpha):
        assert registry._is_blocked("Alpha") is False
        assert registry.is_quarantined("Alpha") is False


# ---------------------------------------------------------------------------
# Violation logging + auto-quarantine
# ---------------------------------------------------------------------------
class TestViolations:
    def test_first_violation_logged_not_quarantined(self, registry, alpha):
        result = registry.record_violation(
            "Alpha", "unauthorized_tool", {"tool_name": "rm"}
        )
        assert result["action_taken"] == "logged"
        assert result["violation_count"] == 1
        assert registry.is_quarantined("Alpha") is False

    def test_third_violation_quarantines(self, registry, alpha):
        for _ in range(QUARANTINE_THRESHOLD - 1):
            registry.record_violation("Alpha", "rate_limit", {})
        result = registry.record_violation("Alpha", "rate_limit", {})
        assert result["action_taken"] == "quarantine"
        assert result["violation_count"] == QUARANTINE_THRESHOLD
        assert registry.is_quarantined("Alpha") is True
        state = registry.get_governance_state("Alpha")
        assert state["status"] == "quarantined"
        assert state["quarantined_at"] is not None

    def test_unknown_violation_type_raises(self, registry, alpha):
        with pytest.raises(ValueError, match="violation_type"):
            registry.record_violation("Alpha", "bogus", {})

    def test_violation_on_unknown_agent_raises(self, registry):
        with pytest.raises(ValueError, match="Unknown agent"):
            registry.record_violation("ghost", "rate_limit", {})

    def test_get_violations_newest_first(self, registry, alpha):
        registry.record_violation("Alpha", "unauthorized_tool", {"n": 1})
        registry.record_violation("Alpha", "unauthorized_path", {"n": 2})
        violations = registry.get_violations("Alpha")
        assert len(violations) == 2
        assert violations[0]["violation_type"] == "unauthorized_path"
        assert violations[0]["details"] == {"n": 2}

    def test_get_violations_excludes_cleared_by_default(self, registry, alpha):
        registry.record_violation("Alpha", "rate_limit", {})
        registry.clear_violations("Alpha", rationale="reviewed")
        assert registry.get_violations("Alpha") == []
        assert len(registry.get_violations("Alpha", include_cleared=True)) == 1


# ---------------------------------------------------------------------------
# Clearing / override
# ---------------------------------------------------------------------------
class TestClearViolations:
    def test_clear_releases_quarantine(self, registry, alpha):
        for _ in range(QUARANTINE_THRESHOLD):
            registry.record_violation("Alpha", "rate_limit", {})
        assert registry.is_quarantined("Alpha") is True

        cleared = registry.clear_violations("Alpha", rationale="manual review")
        assert cleared == QUARANTINE_THRESHOLD
        state = registry.get_governance_state("Alpha")
        assert state["status"] == "active"
        assert state["violation_count"] == 0
        assert state["quarantined_at"] is None

    def test_clear_with_tier_override(self, registry, alpha):
        registry.record_violation("Alpha", "rate_limit", {})
        registry.clear_violations(
            "Alpha", rationale="trusted", override_tier="auto"
        )
        assert registry.get_governance_state("Alpha")["trust_tier"] == "auto"

    def test_clear_with_invalid_tier_raises(self, registry, alpha):
        with pytest.raises(ValueError, match="trust_tier"):
            registry.clear_violations("Alpha", rationale="x", override_tier="god")

    def test_clear_does_not_reactivate_suspended_agent(self, registry, alpha, tmp_path):
        """clear_violations must not turn a 'suspended' status into 'active'."""
        # Manually suspend (bypass facade — no public API for it yet).
        import sqlite3 as _sqlite

        with _sqlite.connect(str(tmp_path / "registry.db")) as conn:
            conn.execute(
                "UPDATE agents SET status = 'suspended' WHERE name = 'Alpha'"
            )
            conn.commit()
        registry.record_violation("Alpha", "rate_limit", {})
        registry.clear_violations("Alpha", rationale="reviewed")
        # Reload state from the store to confirm DB-level value.
        state = registry.store.get_governance_state("Alpha")
        assert state["status"] == "suspended"
        assert state["violation_count"] == 0


# ---------------------------------------------------------------------------
# Trust tier + score
# ---------------------------------------------------------------------------
class TestTrust:
    def test_set_trust_tier(self, registry, alpha):
        registry.set_trust_tier("Alpha", "human")
        assert registry.get_governance_state("Alpha")["trust_tier"] == "human"

    def test_set_trust_tier_invalid(self, registry, alpha):
        with pytest.raises(ValueError):
            registry.set_trust_tier("Alpha", "nonsense")

    def test_set_trust_score_clamped(self, registry, alpha):
        registry.set_trust_score("Alpha", 1.5)
        assert registry.get_governance_state("Alpha")["trust_score"] == 1.0
        registry.set_trust_score("Alpha", -0.2)
        assert registry.get_governance_state("Alpha")["trust_score"] == 0.0


# ---------------------------------------------------------------------------
# Routing excludes blocked agents
# ---------------------------------------------------------------------------
class TestRoutingExcludesBlocked:
    def test_quarantined_agent_excluded(self, registry):
        a = _StubAgent("Alpha", capabilities=["research"])
        b = _StubAgent("Beta", capabilities=["research"])
        registry.register_agent(a)
        registry.register_agent(b)
        registry.scores["Alpha"] = AgentScore(1.0, 1.0, 1.0)  # would win
        for _ in range(QUARANTINE_THRESHOLD):
            registry.record_violation("Alpha", "rate_limit", {})
        # Alpha is quarantined despite the higher score -> Beta routed.
        assert registry.route_task({"required_capability": "research"}) == "Beta"

    def test_all_blocked_raises(self, registry):
        a = _StubAgent("Alpha", capabilities=["research"])
        registry.register_agent(a)
        for _ in range(QUARANTINE_THRESHOLD):
            registry.record_violation("Alpha", "rate_limit", {})
        with pytest.raises(ValueError, match="No agent found"):
            registry.route_task({"required_capability": "research"})


# ---------------------------------------------------------------------------
# Persistence + migration
# ---------------------------------------------------------------------------
class TestPersistenceAndMigration:
    def test_governance_state_survives_reload(self, tmp_path):
        db = str(tmp_path / "registry.db")
        reg1 = AgentRegistry(db_path=db)
        reg1.register_agent(_StubAgent("Alpha", capabilities=["research"]))
        reg1.set_trust_tier("Alpha", "human")
        registry_violation = reg1.record_violation("Alpha", "rate_limit", {})
        assert registry_violation["violation_count"] == 1

        reg2 = AgentRegistry(db_path=db)
        state = reg2.get_governance_state("Alpha")
        assert state["trust_tier"] == "human"
        assert state["violation_count"] == 1

    def test_migration_adds_columns_to_legacy_table(self, tmp_path):
        """A pre-governance agents table is migrated in place on open."""
        db = str(tmp_path / "legacy.db")
        with sqlite3.connect(db) as conn:
            conn.execute(
                "CREATE TABLE agents (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name TEXT UNIQUE NOT NULL, capabilities TEXT NOT NULL, "
                "description TEXT, alignment REAL, accuracy REAL, "
                "efficiency REAL, created_at TEXT, updated_at TEXT)"
            )
            conn.execute(
                "INSERT INTO agents (name, capabilities) VALUES ('Legacy', '[]')"
            )
            conn.commit()

        # Opening through the store should add governance columns.
        registry = AgentRegistry(db_path=db)
        state = registry.store.get_governance_state("Legacy")
        assert state["status"] == "active"
        assert state["trust_tier"] == "monitored"
        assert state["violation_count"] == 0
