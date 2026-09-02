"""Behavioral tests for the Prometheus governance metrics surface."""

import importlib
import sqlite3
import sys

import pytest

from src.integration.agent_registry import AgentRegistryStore
from src.mcp.hebbian_weights import HebbianWeightManager
from src.monitoring.governance_metrics import (
    GovernanceCollector,
    metrics_content_type,
    render_metrics,
)


def _families(collector):
    return {family.name: family for family in collector.collect()}


def _samples(family):
    return {tuple(sample.labels.values()): sample.value for sample in family.samples}


@pytest.fixture
def governance_dbs(tmp_path):
    """Migrated registry and Hebbian stores seeded with governance state."""
    registry_db = str(tmp_path / "agent_registry.db")
    hebbian_db = str(tmp_path / "hebbian_weights.db")

    AgentRegistryStore(db_path=registry_db)
    HebbianWeightManager(db_path=hebbian_db)

    with sqlite3.connect(registry_db) as conn:
        conn.execute(
            "INSERT INTO agents (name, capabilities, status, trust_tier,"
            " violation_count, trust_score) VALUES (?, ?, ?, ?, ?, ?)",
            ("Chat Agent", "[]", "active", "trusted", 0, 0.91),
        )
        conn.execute(
            "INSERT INTO agents (name, capabilities, status, trust_tier,"
            " violation_count, trust_score) VALUES (?, ?, ?, ?, ?, ?)",
            ("Rogue Agent", "[]", "quarantined", "untrusted", 3, 0.12),
        )
        conn.execute(
            "INSERT INTO agents (name, capabilities, status, trust_tier,"
            " violation_count, trust_score) VALUES (?, ?, ?, ?, ?, ?)",
            ("Fresh Agent", "[]", "active", "", 0, None),
        )
        conn.commit()

    with sqlite3.connect(hebbian_db) as conn:
        conn.execute(
            "INSERT INTO hebbian_sentinel_state (agent_name, task_type,"
            " sample_count, sign_changes, oscillation_rate, alert_active,"
            " threshold, window_size, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("Chat Agent", "llm_chat", 20, 11, 0.55, 1, 0.4, 50, "2026-08-17"),
        )
        conn.commit()

    return registry_db, hebbian_db


def test_governance_metrics_collector_reports_registry_and_sentinel_state(
    governance_dbs,
):
    registry_db, hebbian_db = governance_dbs
    collector = GovernanceCollector(registry_db=registry_db, hebbian_db=hebbian_db)

    families = _families(collector)

    trust = _samples(families["artemis_agent_trust_score"])
    assert trust[("Chat Agent", "trusted")] == pytest.approx(0.91)
    assert trust[("Rogue Agent", "untrusted")] == pytest.approx(0.12)
    # Unscored (NULL) agents are omitted instead of coerced to 0.0, so
    # AgentTrustCollapse cannot false-fire on fresh registrations.
    assert not any(labels[0] == "Fresh Agent" for labels in trust)

    violations = _samples(families["artemis_agent_violations"])
    assert violations[("Rogue Agent",)] == 3.0

    statuses = _samples(families["artemis_agents"])
    assert statuses[("active",)] == 2.0
    assert statuses[("quarantined",)] == 1.0
    assert statuses[("suspended",)] == 0.0

    sentinel = _samples(families["artemis_hebbian_sentinel_alert"])
    assert sentinel[("Chat Agent", "llm_chat")] == 1.0

    oscillation = _samples(families["artemis_hebbian_sentinel_oscillation_rate"])
    assert oscillation[("Chat Agent", "llm_chat")] == pytest.approx(0.55)

    scrape_ok = _samples(families["artemis_governance_scrape_ok"])
    assert scrape_ok[("agent_registry",)] == 1.0
    assert scrape_ok[("hebbian_weights",)] == 1.0


def test_governance_metrics_collector_flags_unreadable_stores(tmp_path):
    collector = GovernanceCollector(
        registry_db=str(tmp_path / "missing" / "agent_registry.db"),
        hebbian_db=str(tmp_path / "missing" / "hebbian_weights.db"),
    )

    families = _families(collector)

    scrape_ok = _samples(families["artemis_governance_scrape_ok"])
    assert scrape_ok[("agent_registry",)] == 0.0
    assert scrape_ok[("hebbian_weights",)] == 0.0
    assert _samples(families["artemis_agent_trust_score"]) == {}
    # A scrape must never create governance stores: the read-only URI
    # fails on missing files instead of materializing empty databases.
    assert not (tmp_path / "missing" / "agent_registry.db").exists()
    assert not (tmp_path / "missing" / "hebbian_weights.db").exists()


def test_governance_metrics_reimport_does_not_crash_on_duplicate_registration():
    # Mirrors the ATP/memory-bus guard tests: a sys.modules.pop + reimport
    # must not raise Prometheus' duplicate-registration ValueError.
    import src.monitoring.governance_metrics as gm

    gm.register_governance_collector()
    sys.modules.pop("src.monitoring.governance_metrics", None)
    reimported = importlib.import_module("src.monitoring.governance_metrics")
    reimported.register_governance_collector()
    reimported.register_governance_collector()


def test_governance_metrics_render_produces_exposition_payload(governance_dbs):
    import src.monitoring.governance_metrics as gm

    gm.register_governance_collector()
    payload = render_metrics()
    assert payload
    assert b"artemis_agents" in payload
    assert "text/plain" in metrics_content_type()
