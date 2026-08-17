"""Prometheus exposition for Artemis City governance state.

The governance source of truth lives in SQLite (``data/agent_registry.db``
for trust/status/violations, ``data/hebbian_weights.db`` for the Hebbian
Sentinel). Rather than mutating counters alongside every write, the
collector reads those stores at scrape time, so the exported values can
never drift from what the registry itself would report.

Metric families:

- ``artemis_agent_trust_score{agent,tier}`` — governance trust score per
  registered agent.
- ``artemis_agent_violations{agent}`` — cumulative violation count per
  agent, as recorded by the registry.
- ``artemis_agents{status}`` — number of agents per governance status
  (``active`` / ``suspended`` / ``quarantined``).
- ``artemis_hebbian_sentinel_alert{agent,task_type}`` — 1 while the
  Sentinel holds an active oscillation alert for the scope.
- ``artemis_hebbian_sentinel_oscillation_rate{agent,task_type}`` —
  rolling sign-change rate the Sentinel computed for the scope.
- ``artemis_governance_scrape_ok{store}`` — 1 when the backing store was
  readable during this scrape; 0 signals the alerting layer that the
  governance data itself is unavailable.

Import is guarded the same way as the ATP and memory-bus metrics: without
``prometheus_client`` the module stays importable and the FastAPI layer
reports metrics as unavailable instead of crashing.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Optional

from src.runtime_paths import data_path

try:  # pragma: no cover - exercised implicitly on import
    from prometheus_client import REGISTRY, generate_latest
    from prometheus_client.core import GaugeMetricFamily
    from prometheus_client.exposition import CONTENT_TYPE_LATEST

    METRICS_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    METRICS_AVAILABLE = False
    REGISTRY = None  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]
    GaugeMetricFamily = None  # type: ignore[assignment]
    CONTENT_TYPE_LATEST = "text/plain"

_AGENT_STATUSES = ("active", "suspended", "quarantined")


def _rows(db_file: str, query: str) -> list[tuple]:
    """Run one read-only query against a SQLite file."""
    connection = sqlite3.connect(db_file)
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


class GovernanceCollector:
    """Scrape-time collector over the governance SQLite stores."""

    def __init__(
        self,
        registry_db: Optional[str] = None,
        hebbian_db: Optional[str] = None,
    ):
        self._registry_db_override = registry_db
        self._hebbian_db_override = hebbian_db

    # Paths resolve lazily so a scrape always honors the current
    # ARTEMIS_DATA_DIR / ARTEMIS_REGISTRY_DB / ARTEMIS_HEBBIAN_DB
    # environment, mirroring the stores themselves.
    def _registry_db(self) -> str:
        return data_path(
            "agent_registry.db",
            self._registry_db_override,
            env_var="ARTEMIS_REGISTRY_DB",
        )

    def _hebbian_db(self) -> str:
        return data_path(
            "hebbian_weights.db",
            self._hebbian_db_override,
            env_var="ARTEMIS_HEBBIAN_DB",
        )

    def collect(self) -> Iterable["GaugeMetricFamily"]:
        """Yield governance metric families for the current store state."""
        scrape_ok = GaugeMetricFamily(
            "artemis_governance_scrape_ok",
            "1 when the governance store was readable during this scrape.",
            labels=["store"],
        )

        trust = GaugeMetricFamily(
            "artemis_agent_trust_score",
            "Governance trust score per registered agent.",
            labels=["agent", "tier"],
        )
        violations = GaugeMetricFamily(
            "artemis_agent_violations",
            "Cumulative governance violations recorded per agent.",
            labels=["agent"],
        )
        by_status = GaugeMetricFamily(
            "artemis_agents",
            "Registered agents per governance status.",
            labels=["status"],
        )
        try:
            rows = _rows(
                self._registry_db(),
                "SELECT name, COALESCE(trust_tier, ''), COALESCE(status, 'active'),"
                " COALESCE(violation_count, 0), COALESCE(trust_score, 0.0)"
                " FROM agents",
            )
        except sqlite3.Error:
            scrape_ok.add_metric(["agent_registry"], 0.0)
        else:
            scrape_ok.add_metric(["agent_registry"], 1.0)
            status_counts = {status: 0 for status in _AGENT_STATUSES}
            for name, tier, status, violation_count, trust_score in rows:
                trust.add_metric([str(name), str(tier)], float(trust_score))
                violations.add_metric([str(name)], float(violation_count))
                normalized = str(status).lower()
                if normalized in status_counts:
                    status_counts[normalized] += 1
            for status, count in status_counts.items():
                by_status.add_metric([status], float(count))
        yield trust
        yield violations
        yield by_status

        alert = GaugeMetricFamily(
            "artemis_hebbian_sentinel_alert",
            "1 while the Hebbian Sentinel holds an active alert for the scope.",
            labels=["agent", "task_type"],
        )
        oscillation = GaugeMetricFamily(
            "artemis_hebbian_sentinel_oscillation_rate",
            "Rolling sign-change rate the Hebbian Sentinel computed per scope.",
            labels=["agent", "task_type"],
        )
        try:
            rows = _rows(
                self._hebbian_db(),
                "SELECT agent_name, task_type, alert_active, oscillation_rate"
                " FROM hebbian_sentinel_state",
            )
        except sqlite3.Error:
            scrape_ok.add_metric(["hebbian_weights"], 0.0)
        else:
            scrape_ok.add_metric(["hebbian_weights"], 1.0)
            for agent_name, task_type, alert_active, oscillation_rate in rows:
                labels = [str(agent_name), str(task_type)]
                alert.add_metric(labels, 1.0 if alert_active else 0.0)
                oscillation.add_metric(labels, float(oscillation_rate))
        yield alert
        yield oscillation
        yield scrape_ok


_registered: Optional[GovernanceCollector] = None


def register_governance_collector() -> Optional[GovernanceCollector]:
    """Register the collector on the default registry, once per process.

    Re-imports (the test suite's ``sys.modules.pop`` pattern) and repeat
    calls return the existing collector instead of raising Prometheus'
    duplicate-registration ``ValueError``.
    """
    global _registered
    if not METRICS_AVAILABLE:
        return None
    if _registered is None:
        collector = GovernanceCollector()
        try:
            REGISTRY.register(collector)
        except ValueError:  # already registered by a previous import
            pass
        _registered = collector
    return _registered


def metrics_content_type() -> str:
    """Content type of the Prometheus exposition format in use."""
    return CONTENT_TYPE_LATEST


def render_metrics() -> bytes:
    """Render the default registry in Prometheus exposition format."""
    if not METRICS_AVAILABLE:
        return b""
    return generate_latest(REGISTRY)
