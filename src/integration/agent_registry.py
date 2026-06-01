# src/integration/agent_registry.py

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional
import json
import os
import sqlite3
import time
import uuid

from src.agents import BaseAgent
from src.utils.helpers import logger

# Governance constants — mirror GOVERNANCE.md
TRUST_TIERS = ("auto", "monitored", "human")
AGENT_STATUSES = ("active", "suspended", "quarantined")
VIOLATION_TYPES = (
    "unauthorized_tool",
    "unauthorized_path",
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

    def __init__(self, db_path: str = "data/agent_registry.db"):
        self.db_path = db_path
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
            for name, tier, status, count, quarantined_at, trust_score in cursor.fetchall():
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
        }

    _RECORD_COLUMNS = (
        "name, capabilities, description, alignment, accuracy, efficiency, "
        "trust_tier, status, violation_count, quarantined_at, trust_score"
    )

    def list_agent_records(self) -> List[dict]:
        """Return full persisted records for all agents, ordered by name.
        
        Returns:
            List[dict]: Persisted agent records sorted by agent name.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT {self._RECORD_COLUMNS} FROM agents ORDER BY name ASC"
            ).fetchall()
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
                f"SELECT {self._RECORD_COLUMNS} FROM agents WHERE name = ?",
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
                "SELECT violation_count, status FROM agents WHERE name = ?",
                (agent_name,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown agent: {agent_name!r}")
            current_count, current_status = row
            new_count = (current_count or 0) + 1

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
                    "quarantined_at = ?, updated_at = ? WHERE name = ?",
                    (new_count, new_status, quarantined_at, time.time(), agent_name),
                )
            else:
                conn.execute(
                    "UPDATE agents SET violation_count = ?, updated_at = ? "
                    "WHERE name = ?",
                    (new_count, time.time(), agent_name),
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
                f"Invalid trust_tier {override_tier!r}; "
                f"expected one of {TRUST_TIERS}"
            )

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE violations SET cleared = 1 "
                "WHERE agent_name = ? AND cleared = 0",
                (agent_name,),
            )
            cleared_count = cursor.rowcount

            # Only release quarantine; a 'suspended' status was set for
            # reasons unrelated to violations and must not be cleared here.
            update_fields = [
                "violation_count = 0",
                "status = CASE WHEN status = 'quarantined' THEN 'active' "
                "ELSE status END",
                "quarantined_at = NULL",
                "updated_at = ?",
            ]
            params: list = [time.time()]
            if override_tier is not None:
                update_fields.insert(-1, "trust_tier = ?")
                params.insert(-1, override_tier)
            params.append(agent_name)

            conn.execute(
                f"UPDATE agents SET {', '.join(update_fields)} WHERE name = ?",
                params,
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


class AgentRegistry:
    """Coordinate agent registration, routing, and governance state backed by SQLite.
    """
    def __init__(self, db_path: str = "data/agent_registry.db"):
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
        self.governance[agent.name] = self.store.get_governance_state(agent.name)

    def get_agent(self, agent_name: str) -> BaseAgent:
        """Return agent.
        
        Args:
            agent_name (str): Name of the agent involved in the operation.
        
        Returns:
            BaseAgent: Resulting BaseAgent value produced by the operation.
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
        self.governance[agent_name] = self.store.get_governance_state(agent_name)
        return result

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
        self.governance[agent_name] = self.store.get_governance_state(agent_name)
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
        self.governance[agent_name] = self.store.get_governance_state(agent_name)

    def set_trust_score(self, agent_name: str, score: float):
        """Persist a computed trust score (0.0-1.0).
        
        Args:
            agent_name (str): Name of the agent involved in the operation.
            score (float): Score value being computed or persisted.
        
        Returns:
            None: This function does not return a value.
        """
        self.store.set_trust_score(agent_name, score)
        self.governance[agent_name] = self.store.get_governance_state(agent_name)

    def get_governance_state(self, agent_name: str) -> Optional[dict]:
        """Return cached governance metadata for an agent, or None if unknown.
        
        Args:
            agent_name (str): Agent name to inspect in the in-memory governance cache.
        
        Returns:
            Optional[dict]: Cached governance metadata when available; otherwise None.
        """
        return self.governance.get(agent_name)

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
            result.append(
                {
                    "name": agent.name,
                    "capabilities": agent.capabilities,
                    "alignment": score.alignment,
                    "accuracy": score.accuracy,
                    "efficiency": score.efficiency,
                    "composite_score": score.composite_score,
                }
            )
        return sorted(result, key=lambda x: x["composite_score"], reverse=True)
