# src/integration/agent_registry.py

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.agents.base_agent import BaseAgent
from src.governance.trust import TrustMetrics, compute_trust_score, trust_breakdown
from src.runtime_paths import data_path
from src.utils.helpers import logger

# Governance constants — mirror GOVERNANCE.md
TRUST_TIERS = ("auto", "monitored", "human")
AGENT_STATUSES = ("active", "suspended", "quarantined")
VIOLATION_TYPES = (
    "unauthorized_tool",
    "unauthorized_path",
    "unauthorized_operation",
    "rate_limit",
    "missing_capability",
    "unsafe_network",
)
QUARANTINE_THRESHOLD = 3  # 3rd violation triggers quarantine


def _now_iso() -> str:
    """UTC timestamp in ISO 8601 with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class AgentScore:
    """Store the weighted scoring inputs used to rank an agent during routing.

    Attributes:
        alignment (float): Stored value on the AgentScore instance.
        accuracy (float): Stored value on the AgentScore instance.
        efficiency (float): Stored value on the AgentScore instance.
    """

    alignment: float  # 0.0-1.0 policy adherence
    accuracy: float  # 0.0-1.0 output quality
    efficiency: float  # 0.0-1.0 speed/cost metric

    @property
    def composite_score(self) -> float:
        """Weighted composite score

        Returns:
            float: Numeric result produced by the operation.
        """
        return self.alignment * 0.4 + self.accuracy * 0.4 + self.efficiency * 0.2


class AgentRegistryStore:
    """Lightweight SQLite-backed store for agent registry metadata and scores."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = data_path(
            "agent_registry.db", db_path, env_var="ARTEMIS_REGISTRY_DB"
        )
        self._ensure_db_directory()
        self._initialize_database()

    def _ensure_db_directory(self):
        """Ensure the database directory exists (unless using in-memory)."""
        if self.db_path == ":memory:":
            return
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Created agent registry database directory: {db_dir}")

    def _initialize_database(self):
        """Create the agents and violations tables; apply governance migrations."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    capabilities TEXT NOT NULL,
                    description TEXT,
                    alignment REAL,
                    accuracy REAL,
                    efficiency REAL,
                    created_at TEXT,
                    updated_at TEXT
                )
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS violations (
                    violation_id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    violation_type TEXT NOT NULL,
                    details TEXT NOT NULL,
                    action_taken TEXT NOT NULL,
                    cleared INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (agent_name) REFERENCES agents(name)
                )
                """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_violations_agent "
                "ON violations(agent_name, cleared)"
            )
            self._migrate_governance_columns(conn)
            conn.commit()

    def _migrate_governance_columns(self, conn: sqlite3.Connection):
        """Add governance columns to existing agents tables. Idempotent."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(agents)")}
        migrations = [
            ("trust_tier", "TEXT NOT NULL DEFAULT 'monitored'"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("violation_count", "INTEGER NOT NULL DEFAULT 0"),
            ("quarantined_at", "TEXT"),
            ("trust_score", "REAL"),
            ("execution_count", "INTEGER NOT NULL DEFAULT 0"),
            ("successful_executions", "INTEGER NOT NULL DEFAULT 0"),
            ("failed_executions", "INTEGER NOT NULL DEFAULT 0"),
            ("hebbian_weight", "REAL"),
            ("hebbian_delta", "REAL NOT NULL DEFAULT 0.0"),
            ("hebbian_activations", "INTEGER NOT NULL DEFAULT 0"),
            ("hebbian_success_rate", "REAL NOT NULL DEFAULT 0.0"),
            ("hebbian_task_type", "TEXT"),
            ("hebbian_pair_bonus", "REAL NOT NULL DEFAULT 0.0"),
            ("hebbian_timing_score", "REAL"),
            ("routing_intelligence", "REAL NOT NULL DEFAULT 0.0"),
            ("hebbian_oscillation_rate", "REAL NOT NULL DEFAULT 0.0"),
            ("hebbian_sentinel_alert", "INTEGER NOT NULL DEFAULT 0"),
            ("hebbian_sentinel_samples", "INTEGER NOT NULL DEFAULT 0"),
            ("learning_updated_at", "TEXT"),
        ]
        for column, spec in migrations:
            if column not in existing:
                conn.execute(f"ALTER TABLE agents ADD COLUMN {column} {spec}")

    def load_scores(self) -> Dict[str, AgentScore]:
        """Load persisted scores for all agents.

        Returns:
            Dict[str, AgentScore]: Dictionary containing the resulting data.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT name, alignment, accuracy, efficiency
                FROM agents
                """)
            scores = {}
            for name, alignment, accuracy, efficiency in cursor.fetchall():
                if alignment is None or accuracy is None or efficiency is None:
                    continue
                scores[name] = AgentScore(
                    alignment=alignment,
                    accuracy=accuracy,
                    efficiency=efficiency,
                )
            return scores

    def load_governance_states(self) -> Dict[str, dict]:
        """Load governance metadata (tier, status, violations) for all agents.

        Returns:
            Dict[str, dict]: Dictionary containing the resulting data.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT name, trust_tier, status, violation_count, "
                "quarantined_at, trust_score FROM agents"
            )
            states = {}
            for (
                name,
                tier,
                status,
                count,
                quarantined_at,
                trust_score,
            ) in cursor.fetchall():
                states[name] = {
                    "trust_tier": tier,
                    "status": status,
                    "violation_count": count,
                    "quarantined_at": quarantined_at,
                    "trust_score": trust_score,
                }
            return states

    def _row_to_record(self, row: tuple) -> dict:
        """Shape a full agents row into an API-friendly dict."""
        (
            name,
            capabilities,
            description,
            alignment,
            accuracy,
            efficiency,
            trust_tier,
            status,
            violation_count,
            quarantined_at,
            trust_score,
            execution_count,
            successful_executions,
            failed_executions,
            hebbian_weight,
            hebbian_delta,
            hebbian_activations,
            hebbian_success_rate,
            hebbian_task_type,
            hebbian_pair_bonus,
            hebbian_timing_score,
            routing_intelligence,
            hebbian_oscillation_rate,
            hebbian_sentinel_alert,
            hebbian_sentinel_samples,
            learning_updated_at,
        ) = row
        try:
            caps = json.loads(capabilities) if capabilities else []
        except (json.JSONDecodeError, TypeError):
            caps = []
        if not isinstance(caps, list):
            caps = []
        composite = None
        if None not in (alignment, accuracy, efficiency):
            composite = AgentScore(alignment, accuracy, efficiency).composite_score
        return {
            "name": name,
            "capabilities": caps,
            "description": description,
            "alignment": alignment,
            "accuracy": accuracy,
            "efficiency": efficiency,
            "composite_score": composite,
            "trust_tier": trust_tier,
            "status": status,
            "violation_count": violation_count,
            "quarantined_at": quarantined_at,
            "trust_score": trust_score,
            "execution_count": execution_count,
            "successful_executions": successful_executions,
            "failed_executions": failed_executions,
            "hebbian_weight": hebbian_weight,
            "hebbian_delta": hebbian_delta,
            "hebbian_activations": hebbian_activations,
            "hebbian_success_rate": hebbian_success_rate,
            "hebbian_task_type": hebbian_task_type,
            "hebbian_pair_bonus": hebbian_pair_bonus,
            "hebbian_timing_score": hebbian_timing_score,
            "routing_intelligence": routing_intelligence,
            "hebbian_oscillation_rate": hebbian_oscillation_rate,
            "hebbian_sentinel_alert": bool(hebbian_sentinel_alert),
            "hebbian_sentinel_samples": hebbian_sentinel_samples,
            "learning_updated_at": learning_updated_at,
        }

    _LIST_RECORDS_SQL = """
        SELECT name, capabilities, description, alignment, accuracy, efficiency,
               trust_tier, status, violation_count, quarantined_at, trust_score,
               execution_count, successful_executions, failed_executions,
               hebbian_weight, hebbian_delta, hebbian_activations,
               hebbian_success_rate, hebbian_task_type, hebbian_pair_bonus,
               hebbian_timing_score, routing_intelligence,
               hebbian_oscillation_rate, hebbian_sentinel_alert,
               hebbian_sentinel_samples, learning_updated_at
        FROM agents
        ORDER BY name ASC
    """
    _GET_RECORD_SQL = """
        SELECT name, capabilities, description, alignment, accuracy, efficiency,
               trust_tier, status, violation_count, quarantined_at, trust_score,
               execution_count, successful_executions, failed_executions,
               hebbian_weight, hebbian_delta, hebbian_activations,
               hebbian_success_rate, hebbian_task_type, hebbian_pair_bonus,
               hebbian_timing_score, routing_intelligence,
               hebbian_oscillation_rate, hebbian_sentinel_alert,
               hebbian_sentinel_samples, learning_updated_at
        FROM agents
        WHERE name = ?
    """
    _AGENT_SNAPSHOT_COLUMNS = (
        "id",
        "name",
        "capabilities",
        "description",
        "alignment",
        "accuracy",
        "efficiency",
        "created_at",
        "updated_at",
        "trust_tier",
        "status",
        "violation_count",
        "quarantined_at",
        "trust_score",
        "execution_count",
        "successful_executions",
        "failed_executions",
        "hebbian_weight",
        "hebbian_delta",
        "hebbian_activations",
        "hebbian_success_rate",
        "hebbian_task_type",
        "hebbian_pair_bonus",
        "hebbian_timing_score",
        "routing_intelligence",
        "hebbian_oscillation_rate",
        "hebbian_sentinel_alert",
        "hebbian_sentinel_samples",
        "learning_updated_at",
    )
    _AGENT_SNAPSHOT_DEFAULTS = {
        "id": None,
        "capabilities": "[]",
        "description": None,
        "alignment": None,
        "accuracy": None,
        "efficiency": None,
        "created_at": None,
        "updated_at": None,
        "trust_tier": "monitored",
        "status": "active",
        "violation_count": 0,
        "quarantined_at": None,
        "trust_score": None,
        "execution_count": 0,
        "successful_executions": 0,
        "failed_executions": 0,
        "hebbian_weight": None,
        "hebbian_delta": 0.0,
        "hebbian_activations": 0,
        "hebbian_success_rate": 0.0,
        "hebbian_task_type": None,
        "hebbian_pair_bonus": 0.0,
        "hebbian_timing_score": None,
        "routing_intelligence": 0.0,
        "hebbian_oscillation_rate": 0.0,
        "hebbian_sentinel_alert": 0,
        "hebbian_sentinel_samples": 0,
        "learning_updated_at": None,
    }
    _AGENT_SNAPSHOT_INSERT_SQL = """
        INSERT INTO agents (
            id, name, capabilities, description, alignment, accuracy, efficiency,
            created_at, updated_at, trust_tier, status, violation_count,
            quarantined_at, trust_score, execution_count, successful_executions,
            failed_executions, hebbian_weight, hebbian_delta, hebbian_activations,
            hebbian_success_rate, hebbian_task_type, hebbian_pair_bonus,
            hebbian_timing_score, routing_intelligence, hebbian_oscillation_rate,
            hebbian_sentinel_alert, hebbian_sentinel_samples, learning_updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
    """
    _VIOLATION_SNAPSHOT_COLUMNS = (
        "violation_id",
        "agent_name",
        "timestamp",
        "violation_type",
        "details",
        "action_taken",
        "cleared",
    )
    _VIOLATION_SNAPSHOT_DEFAULTS = {"cleared": 0}
    _VIOLATION_SNAPSHOT_INSERT_SQL = """
        INSERT INTO violations (
            violation_id, agent_name, timestamp, violation_type,
            details, action_taken, cleared
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """

    def list_agent_records(self) -> List[dict]:
        """Return full persisted records for all agents, ordered by name.

        Returns:
            List[dict]: Persisted agent records sorted by agent name.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(self._LIST_RECORDS_SQL).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_agent_record(self, name: str) -> Optional[dict]:
        """Return the full persisted record for one agent, or None.

        Args:
            name (str): Agent name to retrieve from the registry store.

        Returns:
            Optional[dict]: Persisted agent record when found; otherwise None.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                self._GET_RECORD_SQL,
                (name,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def upsert_agent(self, agent: BaseAgent, default_score: AgentScore) -> AgentScore:
        """Insert agent metadata if new; return persisted or default score.

        Args:
            agent (BaseAgent): Agent instance or agent identifier associated with the operation.
            default_score (AgentScore): Fallback score to persist when no score exists yet.

        Returns:
            AgentScore: Resulting AgentScore value produced by the operation.
        """
        capabilities_json = json.dumps(agent.capabilities)
        timestamp = time.time()

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT alignment, accuracy, efficiency FROM agents WHERE name = ?",
                (agent.name,),
            ).fetchone()

            if row:
                # Keep existing scores if present, otherwise fill with defaults
                alignment, accuracy, efficiency = row
                persisted_score = AgentScore(
                    alignment=(
                        alignment if alignment is not None else default_score.alignment
                    ),
                    accuracy=(
                        accuracy if accuracy is not None else default_score.accuracy
                    ),
                    efficiency=(
                        efficiency
                        if efficiency is not None
                        else default_score.efficiency
                    ),
                )
            else:
                persisted_score = default_score

            conn.execute(
                """
                INSERT INTO agents (name, capabilities, description, alignment, accuracy, efficiency, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    capabilities = excluded.capabilities,
                    description = COALESCE(excluded.description, agents.description),
                    updated_at = excluded.updated_at
                """,
                (
                    agent.name,
                    capabilities_json,
                    getattr(agent, "description", None),
                    persisted_score.alignment,
                    persisted_score.accuracy,
                    persisted_score.efficiency,
                    timestamp,
                    timestamp,
                ),
            )
            conn.commit()

        return persisted_score

    def update_score(self, agent_id: str, score: AgentScore):
        """Persist updated score for an agent.

        Args:
            agent_id (str): Identifier of the agent being processed.
            score (AgentScore): Score value being computed or persisted.

        Returns:
            None: This function does not return a value.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE agents
                SET alignment = ?, accuracy = ?, efficiency = ?, updated_at = ?
                WHERE name = ?
                """,
                (
                    score.alignment,
                    score.accuracy,
                    score.efficiency,
                    time.time(),
                    agent_id,
                ),
            )
            conn.commit()

    def record_learning_outcome(
        self,
        agent_name: str,
        *,
        success: bool,
        learning: dict,
    ) -> dict:
        """Atomically mirror execution, Hebbian, and computed trust metrics.

        The trust score uses the authoritative governance formula. Execution
        history and the current violation count are real persisted inputs;
        code-quality, audit, and uptime inputs retain their documented clean
        defaults until those subsystems publish measurements.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT execution_count, successful_executions, "
                "failed_executions, violation_count FROM agents WHERE name = ?",
                (agent_name,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown agent: {agent_name!r}")

            executions = int(row[0] or 0) + 1
            successful = int(row[1] or 0) + (1 if success else 0)
            failed = int(row[2] or 0) + (0 if success else 1)
            metrics = TrustMetrics(
                successful_executions=successful,
                total_executions=executions,
                recent_violation_count=int(row[3] or 0),
            )
            trust_score = compute_trust_score(metrics)
            breakdown = trust_breakdown(metrics)
            updated_at = _now_iso()
            conn.execute(
                """
                UPDATE agents SET
                    execution_count = ?,
                    successful_executions = ?,
                    failed_executions = ?,
                    trust_score = ?,
                    hebbian_weight = ?,
                    hebbian_delta = ?,
                    hebbian_activations = ?,
                    hebbian_success_rate = ?,
                    hebbian_task_type = ?,
                    hebbian_pair_bonus = ?,
                    hebbian_timing_score = ?,
                    routing_intelligence = ?,
                    hebbian_oscillation_rate = ?,
                    hebbian_sentinel_alert = ?,
                    hebbian_sentinel_samples = ?,
                    learning_updated_at = ?,
                    updated_at = ?
                WHERE name = ?
                """,
                (
                    executions,
                    successful,
                    failed,
                    trust_score,
                    learning.get("weight"),
                    learning.get("delta", 0.0),
                    learning.get("activation_count", 0),
                    learning.get("success_rate", 0.0),
                    learning.get("task_type"),
                    learning.get("pair_bonus", 0.0),
                    learning.get("timing_score"),
                    learning.get("routing_intelligence", 0.0),
                    learning.get("oscillation_rate", 0.0),
                    int(bool(learning.get("sentinel_alert", False))),
                    learning.get("sentinel_samples", 0),
                    updated_at,
                    time.time(),
                    agent_name,
                ),
            )
            conn.commit()

        return {
            "trust_score": trust_score,
            "trust_breakdown": breakdown,
            "execution_count": executions,
            "successful_executions": successful,
            "failed_executions": failed,
        }

    def update_learning_snapshot(self, agent_name: str, learning: dict) -> None:
        """Refresh mirrored Hebbian fields without recording an execution."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE agents SET
                    hebbian_weight = ?,
                    hebbian_delta = ?,
                    hebbian_activations = ?,
                    hebbian_success_rate = ?,
                    hebbian_task_type = ?,
                    hebbian_pair_bonus = ?,
                    hebbian_timing_score = ?,
                    routing_intelligence = ?,
                    hebbian_oscillation_rate = ?,
                    hebbian_sentinel_alert = ?,
                    hebbian_sentinel_samples = ?,
                    learning_updated_at = ?,
                    updated_at = ?
                WHERE name = ?
                """,
                (
                    learning.get("weight"),
                    learning.get("delta", 0.0),
                    learning.get("activation_count", 0),
                    learning.get("success_rate", 0.0),
                    learning.get("task_type"),
                    learning.get("pair_bonus", 0.0),
                    learning.get("timing_score"),
                    learning.get("routing_intelligence", 0.0),
                    learning.get("oscillation_rate", 0.0),
                    int(bool(learning.get("sentinel_alert", False))),
                    learning.get("sentinel_samples", 0),
                    _now_iso(),
                    time.time(),
                    agent_name,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown agent: {agent_name!r}")
            conn.commit()

    # ------------------------------------------------------------------
    # Governance — violations, quarantine, trust tier
    # ------------------------------------------------------------------

    def record_violation(
        self,
        agent_name: str,
        violation_type: str,
        details: dict,
    ) -> dict:
        """Log a violation, increment the strike count, and quarantine when the threshold is crossed.

        Args:
            agent_name (str): Name of the agent receiving the violation.
            violation_type (str): Governance violation type to persist.
            details (dict): Structured detail payload recorded with the violation.

        Returns:
            dict: Persisted violation record including the action that was taken.
        """
        if violation_type not in VIOLATION_TYPES:
            raise ValueError(
                f"Unknown violation_type {violation_type!r}; "
                f"expected one of {VIOLATION_TYPES}"
            )

        violation_id = str(uuid.uuid4())
        timestamp = _now_iso()
        details_json = json.dumps(details)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT violation_count, status, execution_count, "
                "successful_executions FROM agents WHERE name = ?",
                (agent_name,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown agent: {agent_name!r}")
            current_count, current_status, executions, successful = row
            new_count = (current_count or 0) + 1
            trust_score = compute_trust_score(
                TrustMetrics(
                    successful_executions=int(successful or 0),
                    total_executions=int(executions or 0),
                    recent_violation_count=new_count,
                )
            )

            if new_count >= QUARANTINE_THRESHOLD and current_status != "quarantined":
                action = "quarantine"
                new_status = "quarantined"
                quarantined_at = timestamp
            else:
                action = "logged"
                new_status = current_status
                quarantined_at = None

            conn.execute(
                "INSERT INTO violations "
                "(violation_id, agent_name, timestamp, violation_type, details, action_taken) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    violation_id,
                    agent_name,
                    timestamp,
                    violation_type,
                    details_json,
                    action,
                ),
            )
            if quarantined_at is not None:
                conn.execute(
                    "UPDATE agents SET violation_count = ?, status = ?, "
                    "quarantined_at = ?, trust_score = ?, updated_at = ? "
                    "WHERE name = ?",
                    (
                        new_count,
                        new_status,
                        quarantined_at,
                        trust_score,
                        time.time(),
                        agent_name,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE agents SET violation_count = ?, trust_score = ?, updated_at = ? "
                    "WHERE name = ?",
                    (new_count, trust_score, time.time(), agent_name),
                )
            conn.commit()

        if action == "quarantine":
            logger.error(
                "Agent %s quarantined after %d violations (latest: %s)",
                agent_name,
                new_count,
                violation_type,
            )

        return {
            "violation_id": violation_id,
            "agent_name": agent_name,
            "timestamp": timestamp,
            "violation_type": violation_type,
            "details": details,
            "action_taken": action,
            "violation_count": new_count,
            "trust_score": trust_score,
        }

    def get_violations(
        self, agent_name: str, include_cleared: bool = False, limit: int = 100
    ) -> List[dict]:
        """Return violations for an agent, newest first.

        Args:
            agent_name (str): Agent name whose violations should be listed.
            include_cleared (bool): Whether cleared violations should remain in the result set.
            limit (int): Maximum number of violation rows to return.

        Returns:
            List[dict]: Serialized violation records ordered from newest to oldest.
        """
        with sqlite3.connect(self.db_path) as conn:
            query = (
                "SELECT violation_id, agent_name, timestamp, violation_type, "
                "details, action_taken, cleared FROM violations "
                "WHERE agent_name = ?"
            )
            params: tuple = (agent_name,)
            if not include_cleared:
                query += " AND cleared = 0"
            query += " ORDER BY timestamp DESC LIMIT ?"
            params = params + (limit,)
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "violation_id": vid,
                "agent_name": name,
                "timestamp": ts,
                "violation_type": vtype,
                "details": json.loads(details),
                "action_taken": action,
                "cleared": bool(cleared),
            }
            for vid, name, ts, vtype, details, action, cleared in rows
        ]

    def clear_violations(
        self,
        agent_name: str,
        rationale: str,
        override_tier: Optional[str] = None,
    ) -> int:
        """Mark active violations as cleared and release quarantine.

        Args:
            agent_name (str): Agent name whose violations should be cleared.
            rationale (str): Human rationale recorded for the override action.
            override_tier (Optional[str]): Optional trust-tier override applied with the clear operation.

        Returns:
            int: Number of violations that were cleared.
        """
        if override_tier is not None and override_tier not in TRUST_TIERS:
            raise ValueError(
                f"Invalid trust_tier {override_tier!r}; expected one of {TRUST_TIERS}"
            )

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE violations SET cleared = 1 "
                "WHERE agent_name = ? AND cleared = 0",
                (agent_name,),
            )
            cleared_count = cursor.rowcount
            execution_row = conn.execute(
                "SELECT execution_count, successful_executions FROM agents "
                "WHERE name = ?",
                (agent_name,),
            ).fetchone()
            cleared_trust = compute_trust_score(
                TrustMetrics(
                    total_executions=int(execution_row[0] or 0) if execution_row else 0,
                    successful_executions=(
                        int(execution_row[1] or 0) if execution_row else 0
                    ),
                    recent_violation_count=0,
                )
            )

            # Only release quarantine; a 'suspended' status was set for
            # reasons unrelated to violations and must not be cleared here.
            timestamp = time.time()
            if override_tier is None:
                conn.execute(
                    """
                    UPDATE agents
                    SET violation_count = 0,
                        trust_score = ?,
                        status = CASE
                            WHEN status = 'quarantined' THEN 'active'
                            ELSE status
                        END,
                        quarantined_at = NULL,
                        updated_at = ?
                    WHERE name = ?
                    """,
                    (cleared_trust, timestamp, agent_name),
                )
            else:
                conn.execute(
                    """
                    UPDATE agents
                    SET violation_count = 0,
                        trust_score = ?,
                        status = CASE
                            WHEN status = 'quarantined' THEN 'active'
                            ELSE status
                        END,
                        quarantined_at = NULL,
                        trust_tier = ?,
                        updated_at = ?
                    WHERE name = ?
                    """,
                    (cleared_trust, override_tier, timestamp, agent_name),
                )
            conn.commit()

        logger.info(
            "Cleared %d violations for agent %s (rationale: %s)",
            cleared_count,
            agent_name,
            rationale,
        )
        return cleared_count

    def set_trust_tier(self, agent_name: str, tier: str):
        """Set the agent's trust tier.

        Args:
            agent_name (str): Name of the agent involved in the operation.
            tier (str): Approval or trust tier value.

        Returns:
            None: This function does not return a value.
        """
        if tier not in TRUST_TIERS:
            raise ValueError(
                f"Invalid trust_tier {tier!r}; expected one of {TRUST_TIERS}"
            )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE agents SET trust_tier = ?, updated_at = ? WHERE name = ?",
                (tier, time.time(), agent_name),
            )
            conn.commit()

    def get_governance_state(self, agent_name: str) -> Optional[dict]:
        """Return all governance metadata for an agent, or None if missing.

        Args:
            agent_name (str): Agent name to inspect in the registry store.

        Returns:
            Optional[dict]: Governance metadata when present; otherwise None.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT trust_tier, status, violation_count, quarantined_at, "
                "trust_score FROM agents WHERE name = ?",
                (agent_name,),
            ).fetchone()
        if row is None:
            return None
        trust_tier, status, violation_count, quarantined_at, trust_score = row
        return {
            "trust_tier": trust_tier,
            "status": status,
            "violation_count": violation_count,
            "quarantined_at": quarantined_at,
            "trust_score": trust_score,
        }

    def set_trust_score(self, agent_name: str, score: float):
        """Persist a computed trust score (0.0-1.0).

        Args:
            agent_name (str): Name of the agent involved in the operation.
            score (float): Score value being computed or persisted.

        Returns:
            None: This function does not return a value.
        """
        score = max(0.0, min(1.0, score))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE agents SET trust_score = ?, updated_at = ? WHERE name = ?",
                (score, time.time(), agent_name),
            )
            conn.commit()

    def export_snapshot(self) -> dict:
        """Return a complete, JSON-serializable registry/governance snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            agents = [dict(row) for row in conn.execute("SELECT * FROM agents")]
            violations = [dict(row) for row in conn.execute("SELECT * FROM violations")]
        return {
            "schema_version": 1,
            "agents": agents,
            "violations": violations,
        }

    def restore_snapshot(self, snapshot: dict) -> dict:
        """Atomically restore a snapshot created by :meth:`export_snapshot`."""
        if not isinstance(snapshot, dict):
            raise ValueError("registry snapshot must be an object")
        agents = snapshot.get("agents")
        violations = snapshot.get("violations")
        if not isinstance(agents, list) or not isinstance(violations, list):
            raise ValueError(
                "registry snapshot must contain agents and violations lists"
            )

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            def _snapshot_values(
                table: str,
                columns: tuple[str, ...],
                defaults: dict,
                row: dict,
            ) -> list:
                if not isinstance(row, dict):
                    raise ValueError(f"{table} snapshot rows must be objects")
                unknown = set(row) - set(columns)
                if unknown:
                    raise ValueError(
                        f"{table} snapshot contains unknown columns: {sorted(unknown)}"
                    )
                if not row:
                    raise ValueError(f"{table} snapshot row is empty")
                return [
                    row[column] if column in row else defaults.get(column)
                    for column in columns
                ]

            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM violations")
            conn.execute("DELETE FROM agents")
            for row in agents:
                conn.execute(
                    self._AGENT_SNAPSHOT_INSERT_SQL,
                    _snapshot_values(
                        "agents",
                        self._AGENT_SNAPSHOT_COLUMNS,
                        self._AGENT_SNAPSHOT_DEFAULTS,
                        row,
                    ),
                )
            for row in violations:
                conn.execute(
                    self._VIOLATION_SNAPSHOT_INSERT_SQL,
                    _snapshot_values(
                        "violations",
                        self._VIOLATION_SNAPSHOT_COLUMNS,
                        self._VIOLATION_SNAPSHOT_DEFAULTS,
                        row,
                    ),
                )
            conn.commit()
        return {"agents": len(agents), "violations": len(violations)}


class AgentRegistry:
    """Coordinate agent registration, routing, and governance state backed by SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        self.store = AgentRegistryStore(db_path=db_path)
        self.agents: Dict[str, BaseAgent] = {}
        self.scores: Dict[str, AgentScore] = self.store.load_scores()
        # Governance cache: name -> {trust_tier, status, violation_count, ...}
        # Authoritative for reads; write-through to the store on mutation.
        self.governance: Dict[str, dict] = self.store.load_governance_states()

    def register_agent(self, agent: BaseAgent):
        """Registers a new agent.

        Args:
            agent (BaseAgent): Agent instance or agent identifier associated with the operation.

        Returns:
            None: This function does not return a value.
        """
        if agent.name in self.agents:
            logger.info(
                f"Agent '{agent.name}' already registered; skipping duplicate registration."
            )
            return
        default_score = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
        persisted_score = self.store.upsert_agent(agent, default_score)
        self.agents[agent.name] = agent
        self.scores[agent.name] = persisted_score
        # Seed governance cache from the freshly-persisted defaults.
        self.governance[agent.name] = self.store.get_governance_state(agent.name) or {}

    def get_agent(self, agent_name: str) -> Optional[BaseAgent]:
        """Return agent, or None if no agent with that name is registered.

        Args:
            agent_name (str): Name of the agent involved in the operation.

        Returns:
            Optional[BaseAgent]: The registered agent, or None if not found.
        """
        return self.agents.get(agent_name)

    # ------------------------------------------------------------------
    # Governance facade — write-through to store, cache in self.governance
    # ------------------------------------------------------------------

    def _is_blocked(self, agent_name: str) -> bool:
        """True if the agent is quarantined or suspended (ineligible for routing)."""
        state = self.governance.get(agent_name)
        if state is None:
            return False
        return state.get("status") in ("quarantined", "suspended")

    def record_violation(
        self, agent_name: str, violation_type: str, details: dict
    ) -> dict:
        """Record a sandbox violation; auto-quarantines on the 3rd strike.

        Args:
            agent_name (str): Name of the agent involved in the operation.
            violation_type (str): Violation type to record or validate.
            details (dict): Structured detail payload recorded with the event.

        Returns:
            dict: Dictionary containing the resulting data.
        """
        result = self.store.record_violation(agent_name, violation_type, details)
        self.governance[agent_name] = self.store.get_governance_state(agent_name) or {}
        return result

    def record_learning_outcome(
        self, agent_name: str, *, success: bool, learning: dict
    ) -> dict:
        """Write through one execution's learning and governance metrics."""
        result = self.store.record_learning_outcome(
            agent_name,
            success=success,
            learning=learning,
        )
        self.governance[agent_name] = self.store.get_governance_state(agent_name) or {}
        return result

    def update_learning_snapshot(self, agent_name: str, learning: dict) -> None:
        """Refresh cached/persisted learning fields without execution counts."""
        self.store.update_learning_snapshot(agent_name, learning)

    def get_violations(
        self, agent_name: str, include_cleared: bool = False, limit: int = 100
    ) -> List[dict]:
        """Return logged violations for an agent, newest first.

        Args:
            agent_name (str): Agent name whose violations should be returned.
            include_cleared (bool): Whether cleared violations should remain in the result set.
            limit (int): Maximum number of violation rows to return.

        Returns:
            List[dict]: Serialized violation records from the registry store.
        """
        return self.store.get_violations(agent_name, include_cleared, limit)

    def clear_violations(
        self, agent_name: str, rationale: str, override_tier: Optional[str] = None
    ) -> int:
        """Clear violations and release quarantine; optionally upgrade trust tier.

        Args:
            agent_name (str): Name of the agent involved in the operation.
            rationale (str): Rationale value used by this operation.
            override_tier (Optional[str]): Optional trust tier override applied during the
                operation.

        Returns:
            int: Integer result produced by the operation.
        """
        cleared = self.store.clear_violations(agent_name, rationale, override_tier)
        self.governance[agent_name] = self.store.get_governance_state(agent_name) or {}
        return cleared

    def set_trust_tier(self, agent_name: str, tier: str):
        """Set the agent's trust tier (auto|monitored|human).

        Args:
            agent_name (str): Name of the agent involved in the operation.
            tier (str): Approval or trust tier value.

        Returns:
            None: This function does not return a value.
        """
        self.store.set_trust_tier(agent_name, tier)
        self.governance[agent_name] = self.store.get_governance_state(agent_name) or {}

    def set_trust_score(self, agent_name: str, score: float):
        """Persist a computed trust score (0.0-1.0).

        Args:
            agent_name (str): Name of the agent involved in the operation.
            score (float): Score value being computed or persisted.

        Returns:
            None: This function does not return a value.
        """
        self.store.set_trust_score(agent_name, score)
        self.governance[agent_name] = self.store.get_governance_state(agent_name) or {}

    def get_governance_state(self, agent_name: str) -> Optional[dict]:
        """Return cached governance metadata for an agent, or None if unknown.

        Args:
            agent_name (str): Agent name to inspect in the in-memory governance cache.

        Returns:
            Optional[dict]: Cached governance metadata when available; otherwise None.
        """
        return self.governance.get(agent_name)

    def export_snapshot(self) -> dict:
        """Return the durable registry snapshot used by governance checkpoints."""
        return self.store.export_snapshot()

    def restore_snapshot(self, snapshot: dict) -> dict:
        """Restore durable state and refresh in-process score/governance caches."""
        result = self.store.restore_snapshot(snapshot)
        self.scores = self.store.load_scores()
        self.governance = self.store.load_governance_states()
        return result

    def is_quarantined(self, agent_name: str) -> bool:
        """Convenience predicate for quarantine status.

        Args:
            agent_name (str): Name of the agent involved in the operation.

        Returns:
            bool: Boolean outcome for the requested check.
        """
        state = self.governance.get(agent_name)
        return bool(state and state.get("status") == "quarantined")

    def route_task(self, task: dict) -> str:
        """Route task to highest-scoring capable agent.

        Quarantined and suspended agents are excluded from routing.

        Args:
            task (dict): Task payload being routed or updated.

        Returns:
            str: String result produced by the operation.
        """
        required_capability = task.get("required_capability")
        if not required_capability:
            raise ValueError(
                "Task dictionary must contain a 'required_capability' key."
            )

        candidates = [
            agent.name
            for agent in self.agents.values()
            if required_capability in agent.capabilities
            and not self._is_blocked(agent.name)
        ]

        if not candidates:
            raise ValueError(
                f"No agent found with the required capability: {required_capability}"
            )

        # Sort by composite score
        best_agent_name = max(
            candidates, key=lambda agent_name: self.scores[agent_name].composite_score
        )

        return best_agent_name

    def update_score(self, agent_id: str, dimension: str, delta: float):
        """Update agent score dimension with decay

        Args:
            agent_id (str): Identifier of the agent being processed.
            dimension (str): Score dimension to update.
            delta (float): Delta to apply to the selected score dimension.

        Returns:
            None: This function does not return a value.
        """
        if agent_id not in self.scores:
            return

        current_score = getattr(self.scores[agent_id], dimension)
        # Applying a simple decay-like update, could be more sophisticated
        new_score = max(0.0, min(1.0, current_score + delta))
        setattr(self.scores[agent_id], dimension, new_score)

        self._log_score_change(agent_id, dimension, current_score, new_score)
        self.store.update_score(agent_id, self.scores[agent_id])

    def _log_score_change(self, agent_id, dimension, old_score, new_score):
        logger.info(
            "Score update for %s: %s changed from %.2f to %.2f",
            agent_id,
            dimension,
            old_score,
            new_score,
        )

    def get_all_agents(self) -> List[BaseAgent]:
        """Return all agents.

        Returns:
            List[BaseAgent]: List containing the resulting items.
        """
        return list(self.agents.values())

    def get_agent_names(self) -> List[str]:
        """Return agent names.

        Returns:
            List[str]: List containing the resulting items.
        """
        return list(self.agents.keys())

    def get_all_agents_with_scores(self) -> List[Dict]:
        """Return all agents with their capabilities and performance scores.

        Returns:
            List[Dict]: Agent score records sorted by composite score in descending order.
        """
        result = []
        for agent in self.agents.values():
            score = self.scores.get(agent.name, AgentScore(0.5, 0.5, 0.5))
            persisted = self.store.get_agent_record(agent.name) or {}
            result.append(
                {
                    "name": agent.name,
                    "capabilities": agent.capabilities,
                    "alignment": score.alignment,
                    "accuracy": score.accuracy,
                    "efficiency": score.efficiency,
                    "composite_score": score.composite_score,
                    "trust_score": persisted.get("trust_score"),
                    "execution_count": persisted.get("execution_count", 0),
                    "successful_executions": persisted.get("successful_executions", 0),
                    "failed_executions": persisted.get("failed_executions", 0),
                    "hebbian_weight": persisted.get("hebbian_weight"),
                    "hebbian_delta": persisted.get("hebbian_delta", 0.0),
                    "hebbian_activations": persisted.get("hebbian_activations", 0),
                    "hebbian_success_rate": persisted.get("hebbian_success_rate", 0.0),
                    "hebbian_task_type": persisted.get("hebbian_task_type"),
                    "hebbian_pair_bonus": persisted.get("hebbian_pair_bonus", 0.0),
                    "hebbian_timing_score": persisted.get("hebbian_timing_score"),
                    "routing_intelligence": persisted.get("routing_intelligence", 0.0),
                }
            )
        return sorted(result, key=lambda x: x["composite_score"], reverse=True)
