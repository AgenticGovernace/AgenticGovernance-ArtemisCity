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
from urllib.parse import quote

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
    """Run one query against a SQLite file, strictly read-only.

    A plain ``sqlite3.connect(path)`` would CREATE an empty database when
    the store does not exist yet (e.g. the SQLite-only fallback before
    first orchestrator boot) — a Prometheus scrape must never mutate
    governance storage. ``mode=ro`` makes a missing store raise instead,
    which the collector reports via ``artemis_governance_scrape_ok``.
    """
    connection = sqlite3.connect(f"file:{quote(db_file)}?mode=ro", uri=True)
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
                " COALESCE(violation_count, 0), trust_score"
                " FROM agents",
            )
        except sqlite3.Error:
            scrape_ok.add_metric(["agent_registry"], 0.0)
        else:
            scrape_ok.add_metric(["agent_registry"], 1.0)
            status_counts = {status: 0 for status in _AGENT_STATUSES}
            for name, tier, status, violation_count, trust_score in rows:
                # Newly registered agents carry trust_score = NULL until a
                # trust calculation persists; omit them rather than coercing
                # to 0.0, which would false-fire AgentTrustCollapse.
                if trust_score is not None:
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


def governance_snapshot(
    registry_db: Optional[str] = None,
    hebbian_db: Optional[str] = None,
) -> dict:
    """JSON-ready governance state for the dashboard monitoring page.

    Reads the same stores as :class:`GovernanceCollector`, with the same
    strictly read-only access, but keeps per-agent status alongside trust
    and violations so the frontend can render one table without joining
    metric families. ``stores`` mirrors ``artemis_governance_scrape_ok``.
    """
    collector = GovernanceCollector(registry_db=registry_db, hebbian_db=hebbian_db)
    agents: list[dict] = []
    status_counts = {status: 0 for status in _AGENT_STATUSES}
    stores = {"agent_registry": False, "hebbian_weights": False}
    try:
        rows = _rows(
            collector._registry_db(),
            "SELECT name, COALESCE(trust_tier, ''), COALESCE(status, 'active'),"
            " COALESCE(violation_count, 0), trust_score"
            " FROM agents ORDER BY name",
        )
    except sqlite3.Error:
        pass
    else:
        stores["agent_registry"] = True
        for name, tier, status, violation_count, trust_score in rows:
            normalized = str(status).lower()
            if normalized in status_counts:
                status_counts[normalized] += 1
            agents.append(
                {
                    "name": str(name),
                    "tier": str(tier),
                    "status": normalized,
                    "violations": int(violation_count),
                    "trust_score": (
                        float(trust_score) if trust_score is not None else None
                    ),
                }
            )

    sentinel: list[dict] = []
    try:
        rows = _rows(
            collector._hebbian_db(),
            "SELECT agent_name, task_type, alert_active, oscillation_rate,"
            " sample_count, threshold"
            " FROM hebbian_sentinel_state ORDER BY agent_name, task_type",
        )
    except sqlite3.Error:
        pass
    else:
        stores["hebbian_weights"] = True
        for (
            agent_name,
            task_type,
            alert_active,
            oscillation_rate,
            samples,
            threshold,
        ) in rows:
            sentinel.append(
                {
                    "agent": str(agent_name),
                    "task_type": str(task_type),
                    "alert_active": bool(alert_active),
                    "oscillation_rate": float(oscillation_rate),
                    "sample_count": int(samples),
                    "threshold": float(threshold),
                }
            )

    return {
        "agents": agents,
        "status_counts": status_counts,
        "sentinel": sentinel,
        "stores": stores,
    }


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
