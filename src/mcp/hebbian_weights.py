"""Persistent Hebbian learning engine for Artemis City.

The production outcome path implements the full rule prototyped in
``SIMULATION DOC.ipynb``:

* success: ``delta = tanh(learning_rate * performance)``
* failure: ``delta = -learning_rate`` (anti-Hebbian update)
* global decay: ``weight = max(floor, (weight + delta) * decay)``
* sequential agent-pair reinforcement for successful hand-offs
* a rolling 30-observation timing/performance signal
* persisted compounding-value metrics (individual entropy + pair value +
  timing diversity)

The historical ``strengthen_connection`` / ``weaken_connection`` methods are
retained as compatibility primitives for callers that deliberately request a
fixed increment. Runtime orchestration uses :meth:`record_outcome`.
"""

import math
import os
import sqlite3
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.runtime_paths import data_path
from src.utils.helpers import logger

# Lazy import to avoid circular dependency
_run_logger = None

DEFAULT_LEARNING_RATE = 0.1
DEFAULT_DECAY = 0.99
DEFAULT_WEIGHT = 1.0
WEIGHT_FLOOR = 0.01
PAIR_PERFORMANCE_FLOOR = 0.3
TIMING_WINDOW = 30
TIMING_WARMUP = 5


@dataclass(frozen=True)
class HebbianUpdate:
    """Serializable result of one full Hebbian outcome update."""

    agent_name: str
    task_id: str
    task_type: Optional[str]
    success: bool
    performance: float
    weight: float
    delta: float
    activation_count: int
    success_rate: float
    pair_bonus: float
    timing_score: float
    individual_information: float
    pair_information: float
    timing_information: float
    routing_intelligence: float

    def to_dict(self) -> dict:
        """Return the persisted/API form of this update."""
        return dict(self.__dict__)


def _get_run_logger():
    """Lazy load run logger to avoid circular imports."""
    global _run_logger
    if _run_logger is None:
        try:
            from src.utils import get_run_logger

            _run_logger = get_run_logger()
        except Exception:
            _run_logger = None
    return _run_logger


class HebbianWeightManager:
    """
    Manages connection weights between nodes (agents, tasks, outputs) using Hebbian learning.

    Runtime updates use nonlinear performance reinforcement, anti-Hebbian
    failure penalties, decay, pair learning, and timing memory. Fixed +/-1
    helpers remain available for compatibility and manual diagnostics.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize Hebbian weight manager with SQLite backend.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = data_path(
            "hebbian_weights.db", db_path, env_var="ARTEMIS_HEBBIAN_DB"
        )
        self._ensure_db_directory()
        self._initialize_database()
        logger.info("HebbianWeightManager initialized with database: %s", self.db_path)

    def _ensure_db_directory(self):
        """Ensure the data directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"Created directory for Hebbian weights: {db_dir}")

    def _initialize_database(self):
        """Create and migrate every table owned by the Hebbian engine."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS node_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    origin_node TEXT NOT NULL,
                    target_node TEXT NOT NULL,
                    weight REAL DEFAULT 0,
                    activation_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_updated TEXT,
                    created_at TEXT,
                    UNIQUE(origin_node, target_node)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_origin
                ON node_connections(origin_node)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weight
                ON node_connections(weight DESC)
            """)
            existing = {
                row[1] for row in conn.execute("PRAGMA table_info(node_connections)")
            }
            for column, spec in (
                ("last_delta", "REAL NOT NULL DEFAULT 0.0"),
                ("last_performance", "REAL NOT NULL DEFAULT 0.0"),
            ):
                if column not in existing:
                    conn.execute(
                        f"ALTER TABLE node_connections ADD COLUMN {column} {spec}"
                    )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_pair_weights (
                    previous_agent TEXT NOT NULL,
                    current_agent TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 0.0,
                    activation_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_delta REAL NOT NULL DEFAULT 0.0,
                    last_updated TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (previous_agent, current_agent)
                )
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_timing_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    duration_ms REAL,
                    performance REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timing_agent_type
                ON agent_timing_samples(agent_name, task_type, id DESC)
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_timing_metrics (
                    agent_name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    avg_duration_ms REAL,
                    avg_performance REAL NOT NULL DEFAULT 0.0,
                    timing_score REAL NOT NULL DEFAULT 0.5,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (agent_name, task_type)
                )
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hebbian_engine_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    last_agent TEXT,
                    last_performance REAL,
                    updated_at TEXT
                )
                """)
            conn.execute("""
                INSERT OR IGNORE INTO hebbian_engine_state
                    (singleton, last_agent, last_performance, updated_at)
                VALUES (1, NULL, NULL, NULL)
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hebbian_learning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    task_type TEXT,
                    success INTEGER NOT NULL,
                    performance REAL NOT NULL,
                    delta REAL NOT NULL,
                    resulting_weight REAL NOT NULL,
                    pair_delta REAL NOT NULL DEFAULT 0.0,
                    duration_ms REAL,
                    individual_information REAL NOT NULL DEFAULT 0.0,
                    pair_information REAL NOT NULL DEFAULT 0.0,
                    timing_information REAL NOT NULL DEFAULT 0.0,
                    routing_intelligence REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL
                )
                """)
            conn.commit()

    @staticmethod
    def _clamp_activation(value: float) -> float:
        """Clamp an activation/performance value to the simulation range."""
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _connection_targets(task_id: str, task_type: Optional[str]) -> List[str]:
        targets = [str(task_id)]
        if task_type:
            scoped = HebbianWeightManager.task_type_target(task_type)
            if scoped not in targets:
                targets.append(scoped)
        return targets

    def record_outcome(
        self,
        agent_name: str,
        task_id: str,
        *,
        success: bool,
        performance: float,
        task_type: Optional[str] = None,
        duration_ms: Optional[float] = None,
        learning_rate: float = DEFAULT_LEARNING_RATE,
        decay: float = DEFAULT_DECAY,
        weight_floor: float = WEIGHT_FLOOR,
    ) -> dict:
        """Persist one complete simulation-aligned learning update.

        Task-id and task-type connections are updated in one transaction and
        the network is decayed exactly once. The selected task-type edge is
        the routing source of truth; task-id edges preserve per-run lineage.
        """
        start_time = time.perf_counter()
        performance = self._clamp_activation(performance)
        learning_rate = max(0.0, float(learning_rate))
        decay = max(0.0, min(1.0, float(decay)))
        weight_floor = max(0.0, float(weight_floor))
        delta = math.tanh(learning_rate * performance) if success else -learning_rate
        targets = self._connection_targets(task_id, task_type)
        now = datetime.now().isoformat()
        pair_delta = 0.0

        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")

            # The notebook decays the whole individual network after each
            # activation. Applying decay first and then adding delta*decay is
            # algebraically identical to (weight + delta) * decay.
            conn.execute(
                "UPDATE node_connections SET weight = MAX(?, weight * ?)",
                (weight_floor, decay),
            )

            updated_rows: Dict[str, sqlite3.Row] = {}
            for target in targets:
                row = conn.execute(
                    "SELECT weight FROM node_connections "
                    "WHERE origin_node = ? AND target_node = ?",
                    (agent_name, target),
                ).fetchone()
                decayed_weight = (
                    float(row["weight"])
                    if row is not None
                    else max(weight_floor, DEFAULT_WEIGHT * decay)
                )
                new_weight = max(weight_floor, decayed_weight + delta * decay)
                conn.execute(
                    """
                    INSERT INTO node_connections (
                        origin_node, target_node, weight, activation_count,
                        success_count, failure_count, last_updated, created_at,
                        last_delta, last_performance
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(origin_node, target_node) DO UPDATE SET
                        weight = excluded.weight,
                        activation_count = node_connections.activation_count + 1,
                        success_count = node_connections.success_count + excluded.success_count,
                        failure_count = node_connections.failure_count + excluded.failure_count,
                        last_updated = excluded.last_updated,
                        last_delta = excluded.last_delta,
                        last_performance = excluded.last_performance
                    """,
                    (
                        agent_name,
                        target,
                        new_weight,
                        1 if success else 0,
                        0 if success else 1,
                        now,
                        now,
                        delta,
                        performance,
                    ),
                )
                updated_rows[target] = conn.execute(
                    "SELECT * FROM node_connections "
                    "WHERE origin_node = ? AND target_node = ?",
                    (agent_name, target),
                ).fetchone()

            state = conn.execute(
                "SELECT last_agent, last_performance FROM hebbian_engine_state "
                "WHERE singleton = 1"
            ).fetchone()
            previous_agent = state["last_agent"] if state else None
            previous_performance = (
                float(state["last_performance"])
                if state and state["last_performance"] is not None
                else None
            )
            if previous_agent and previous_performance is not None:
                pair_rate = learning_rate * 0.5
                if (
                    previous_performance > PAIR_PERFORMANCE_FLOOR
                    and performance > PAIR_PERFORMANCE_FLOOR
                ):
                    pair_delta = math.tanh(
                        pair_rate * previous_performance * performance
                    )
                    pair_success = 1
                else:
                    pair_delta = -(pair_rate * 0.5)
                    pair_success = 0
                conn.execute(
                    """
                    INSERT INTO agent_pair_weights (
                        previous_agent, current_agent, weight, activation_count,
                        success_count, failure_count, last_delta, last_updated,
                        created_at
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(previous_agent, current_agent) DO UPDATE SET
                        weight = agent_pair_weights.weight + excluded.weight,
                        activation_count = agent_pair_weights.activation_count + 1,
                        success_count = agent_pair_weights.success_count + excluded.success_count,
                        failure_count = agent_pair_weights.failure_count + excluded.failure_count,
                        last_delta = excluded.last_delta,
                        last_updated = excluded.last_updated
                    """,
                    (
                        previous_agent,
                        agent_name,
                        pair_delta,
                        pair_success,
                        0 if pair_success else 1,
                        pair_delta,
                        now,
                        now,
                    ),
                )

            conn.execute(
                "UPDATE hebbian_engine_state SET last_agent = ?, "
                "last_performance = ?, updated_at = ? WHERE singleton = 1",
                (agent_name, performance, now),
            )

            timing_type = str(task_type or "<unspecified>")
            conn.execute(
                "INSERT INTO agent_timing_samples "
                "(agent_name, task_type, duration_ms, performance, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (agent_name, timing_type, duration_ms, performance, now),
            )
            conn.execute(
                """
                DELETE FROM agent_timing_samples
                WHERE agent_name = ? AND task_type = ? AND id NOT IN (
                    SELECT id FROM agent_timing_samples
                    WHERE agent_name = ? AND task_type = ?
                    ORDER BY id DESC LIMIT ?
                )
                """,
                (agent_name, timing_type, agent_name, timing_type, TIMING_WINDOW),
            )
            timing = conn.execute(
                "SELECT COUNT(*) AS n, AVG(duration_ms) AS avg_duration, "
                "AVG(performance) AS avg_performance "
                "FROM agent_timing_samples WHERE agent_name = ? AND task_type = ?",
                (agent_name, timing_type),
            ).fetchone()
            sample_count = int(timing["n"])
            avg_performance = float(timing["avg_performance"] or 0.0)
            timing_score = avg_performance if sample_count >= TIMING_WARMUP else 0.5
            conn.execute(
                """
                INSERT INTO agent_timing_metrics (
                    agent_name, task_type, sample_count, avg_duration_ms,
                    avg_performance, timing_score, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_name, task_type) DO UPDATE SET
                    sample_count = excluded.sample_count,
                    avg_duration_ms = excluded.avg_duration_ms,
                    avg_performance = excluded.avg_performance,
                    timing_score = excluded.timing_score,
                    updated_at = excluded.updated_at
                """,
                (
                    agent_name,
                    timing_type,
                    sample_count,
                    timing["avg_duration"],
                    avg_performance,
                    timing_score,
                    now,
                ),
            )

            metrics = self._compounding_metrics(conn)
            primary_target = (
                self.task_type_target(task_type) if task_type else str(task_id)
            )
            primary = updated_rows[primary_target]
            weight = float(primary["weight"])
            activations = int(primary["activation_count"])
            success_rate = (
                float(primary["success_count"]) / activations if activations else 0.0
            )
            conn.execute(
                """
                INSERT INTO hebbian_learning_events (
                    agent_name, task_id, task_type, success, performance, delta,
                    resulting_weight, pair_delta, duration_ms,
                    individual_information, pair_information, timing_information,
                    routing_intelligence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_name,
                    str(task_id),
                    task_type,
                    int(success),
                    performance,
                    delta,
                    weight,
                    pair_delta,
                    duration_ms,
                    metrics["individual_information"],
                    metrics["pair_information"],
                    metrics["timing_information"],
                    metrics["routing_intelligence"],
                    now,
                ),
            )
            conn.commit()

        update = HebbianUpdate(
            agent_name=agent_name,
            task_id=str(task_id),
            task_type=task_type,
            success=bool(success),
            performance=performance,
            weight=weight,
            delta=delta,
            activation_count=activations,
            success_rate=success_rate,
            pair_bonus=pair_delta,
            timing_score=timing_score,
            individual_information=metrics["individual_information"],
            pair_information=metrics["pair_information"],
            timing_information=metrics["timing_information"],
            routing_intelligence=metrics["routing_intelligence"],
        )

        latency_ms = (time.perf_counter() - start_time) * 1000
        run_logger = _get_run_logger()
        if run_logger:
            run_logger.log_hebbian_update(
                origin=agent_name,
                target=primary_target,
                operation="nonlinear_reinforce" if success else "anti_hebbian",
                old_weight=weight - delta,
                new_weight=weight,
                latency_ms=latency_ms,
            )
        return update.to_dict()

    @staticmethod
    def _compounding_metrics(conn: sqlite3.Connection) -> dict:
        """Calculate the notebook's persisted compounding-value signals."""
        rows = conn.execute(
            "SELECT weight FROM node_connections "
            "WHERE target_node LIKE 'task_type:%' AND weight > 0"
        ).fetchall()
        weights = [float(row[0]) for row in rows]
        total_weight = sum(weights)
        individual_information = 0.0
        if total_weight > 0:
            probabilities = [weight / total_weight for weight in weights]
            individual_information = -sum(
                probability * math.log(probability)
                for probability in probabilities
                if probability > 0
            )

        pair_row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN weight > 0 THEN weight ELSE 0 END), 0) "
            "FROM agent_pair_weights"
        ).fetchone()
        pair_information = float(pair_row[0] or 0.0)
        timing_scores = [
            float(row[0])
            for row in conn.execute(
                "SELECT timing_score FROM agent_timing_metrics"
            ).fetchall()
        ]
        timing_information = (
            statistics.pstdev(timing_scores) if len(timing_scores) > 1 else 0.0
        )
        return {
            "individual_information": individual_information,
            "pair_information": pair_information,
            "timing_information": timing_information,
            "routing_intelligence": (
                individual_information + pair_information + timing_information
            ),
        }

    def get_pair_bonus(self, agent_name: str) -> float:
        """Return the normalized pair-synergy bonus from the last active agent."""
        with sqlite3.connect(self.db_path) as conn:
            state = conn.execute(
                "SELECT last_agent FROM hebbian_engine_state WHERE singleton = 1"
            ).fetchone()
            if not state or not state[0]:
                return 0.0
            rows = conn.execute(
                "SELECT current_agent, weight FROM agent_pair_weights "
                "WHERE previous_agent = ?",
                (state[0],),
            ).fetchall()
        if not rows:
            return 0.0
        maximum = max(abs(float(row[1])) for row in rows)
        if maximum <= 0:
            return 0.0
        weights = {str(row[0]): float(row[1]) for row in rows}
        return (weights.get(agent_name, 0.0) / maximum) * 0.5

    def get_timing_score(self, agent_name: str, task_type: str) -> Optional[float]:
        """Return the rolling timing/performance score for an agent/task type."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT timing_score FROM agent_timing_metrics "
                "WHERE agent_name = ? AND task_type = ?",
                (agent_name, str(task_type or "<unspecified>")),
            ).fetchone()
        return float(row[0]) if row else None

    def get_compounding_value(self) -> dict:
        """Return current routing-intelligence metrics."""
        with sqlite3.connect(self.db_path) as conn:
            return self._compounding_metrics(conn)

    def get_agent_learning_summary(
        self, agent_name: str, task_type: Optional[str] = None
    ) -> dict:
        """Return the Hebbian fields mirrored into the agent registry."""
        target = self.task_type_target(task_type) if task_type else None
        stats = self.get_connection_stats(agent_name, target) if target else None
        if stats is None:
            weight = self.get_agent_average_weight(agent_name)
            activations = 0
            success_rate = self.get_agent_success_rate(agent_name)
            delta = 0.0
        else:
            weight = float(stats["weight"])
            activations = int(stats["activation_count"])
            success_rate = (
                float(stats["success_count"]) / activations if activations else 0.0
            )
            delta = float(stats.get("last_delta") or 0.0)
        metrics = self.get_compounding_value()
        return {
            "weight": weight,
            "delta": delta,
            "activation_count": activations,
            "success_rate": success_rate,
            "task_type": task_type,
            "pair_bonus": self.get_pair_bonus(agent_name),
            "timing_score": (
                self.get_timing_score(agent_name, task_type) if task_type else None
            ),
            **metrics,
        }

    def strengthen_connection(self, origin: str, target: str) -> float:
        """
        Strengthen connection between two nodes (Hebbian reinforcement).
        Update rule: ΔW = +1

        Args:
            origin: Origin node (e.g., "Artemis Agent")
            target: Target node (e.g., "task_T123")

        Returns:
            New weight value
        """
        start_time = time.perf_counter()
        current_weight = self.get_weight(origin, target)
        new_weight = current_weight + 1

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO node_connections
                    (origin_node, target_node, weight, activation_count, success_count,
                     last_updated, created_at)
                VALUES (?, ?, ?, 1, 1, ?, ?)
                ON CONFLICT(origin_node, target_node)
                DO UPDATE SET
                    weight = weight + 1,
                    activation_count = activation_count + 1,
                    success_count = success_count + 1,
                    last_updated = ?
            """,
                (
                    origin,
                    target,
                    new_weight,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            f"Hebbian: Strengthened {origin} → {target} (weight: {new_weight}, {latency_ms:.2f}ms)"
        )

        # Log to run logger
        run_logger = _get_run_logger()
        if run_logger:
            run_logger.log_hebbian_update(
                origin=origin,
                target=target,
                operation="strengthen",
                old_weight=current_weight,
                new_weight=new_weight,
                latency_ms=latency_ms,
            )

        return new_weight

    def weaken_connection(self, origin: str, target: str) -> float:
        """
        Weaken connection between two nodes (Anti-Hebbian pruning).
        Update rule: ΔW = -1 (minimum 0)

        Args:
            origin: Origin node
            target: Target node

        Returns:
            New weight value
        """
        start_time = time.perf_counter()
        current_weight = self.get_weight(origin, target)
        new_weight = max(0, current_weight - 1)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO node_connections
                    (origin_node, target_node, weight, activation_count, failure_count,
                     last_updated, created_at)
                VALUES (?, ?, ?, 1, 1, ?, ?)
                ON CONFLICT(origin_node, target_node)
                DO UPDATE SET
                    weight = MAX(0, weight - 1),
                    activation_count = activation_count + 1,
                    failure_count = failure_count + 1,
                    last_updated = ?
            """,
                (
                    origin,
                    target,
                    new_weight,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            f"Hebbian: Weakened {origin} → {target} (weight: {new_weight}, {latency_ms:.2f}ms)"
        )

        # Log to run logger
        run_logger = _get_run_logger()
        if run_logger:
            run_logger.log_hebbian_update(
                origin=origin,
                target=target,
                operation="weaken",
                old_weight=current_weight,
                new_weight=new_weight,
                latency_ms=latency_ms,
            )

        return new_weight

    def get_weight(self, origin: str, target: str) -> float:
        """
        Get current weight between two nodes.

        Args:
            origin: Origin node
            target: Target node

        Returns:
            Current weight (0 if connection doesn't exist)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT weight FROM node_connections
                WHERE origin_node = ? AND target_node = ?
            """,
                (origin, target),
            )
            result = cursor.fetchone()
            return result[0] if result else 0.0

    def get_connection_stats(self, origin: str, target: str) -> Optional[dict]:
        """
        Get detailed statistics for a specific connection.

        Args:
            origin: Origin node
            target: Target node

        Returns:
            Dictionary with connection statistics or None
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM node_connections
                WHERE origin_node = ? AND target_node = ?
            """,
                (origin, target),
            )
            result = cursor.fetchone()
            return dict(result) if result else None

    def get_strongest_connections(
        self, node: str, limit: int = 10, direction: str = "outgoing"
    ) -> List[Tuple[str, float]]:
        """
        Get strongest connections for a node.

        Args:
            node: Node to query
            limit: Maximum number of connections to return
            direction: "outgoing" (origin) or "incoming" (target)

        Returns:
            List of (connected_node, weight) tuples
        """
        with sqlite3.connect(self.db_path) as conn:
            if direction == "outgoing":
                cursor = conn.execute(
                    """
                    SELECT target_node, weight FROM node_connections
                    WHERE origin_node = ?
                    ORDER BY weight DESC
                    LIMIT ?
                """,
                    (node, limit),
                )
            else:  # incoming
                cursor = conn.execute(
                    """
                    SELECT origin_node, weight FROM node_connections
                    WHERE target_node = ?
                    ORDER BY weight DESC
                    LIMIT ?
                """,
                    (node, limit),
                )

            return cursor.fetchall()

    def get_agent_average_weight(self, agent_name: str) -> float:
        """
        Calculate average weight for all connections from an agent.
        Used for agent viability scoring.

        Args:
            agent_name: Name of the agent

        Returns:
            Average weight across all connections
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT AVG(weight) FROM node_connections
                WHERE origin_node = ?
            """,
                (agent_name,),
            )
            result = cursor.fetchone()
            return result[0] if result[0] is not None else 0.0

    @staticmethod
    def task_type_target(task_type: str) -> str:
        """Return the persistent node key for a routable task type."""
        normalized = str(task_type).strip()
        if not normalized:
            raise ValueError("task_type must be a non-empty string")
        return f"task_type:{normalized}"

    def get_task_type_weight(self, agent_name: str, task_type: str) -> Optional[float]:
        """Return an agent's learned weight for one task type.

        ``None`` means that the agent has no scoped history yet. This is
        intentionally different from ``0.0``, which is a real learned weight
        after one or more failed activations.
        """
        stats = self.get_connection_stats(agent_name, self.task_type_target(task_type))
        return float(stats["weight"]) if stats is not None else None

    def has_task_type_history(self, agent_name: str) -> bool:
        """Return whether an agent has any capability-scoped connections."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM node_connections
                WHERE origin_node = ? AND target_node LIKE 'task_type:%'
                LIMIT 1
                """,
                (agent_name,),
            ).fetchone()
            return row is not None

    def strengthen_task_type(self, agent_name: str, task_type: str) -> float:
        """Strengthen an agent-to-task-type connection after success."""
        return self.strengthen_connection(agent_name, self.task_type_target(task_type))

    def weaken_task_type(self, agent_name: str, task_type: str) -> float:
        """Weaken an agent-to-task-type connection after failure."""
        return self.weaken_connection(agent_name, self.task_type_target(task_type))

    def get_agent_success_rate(self, agent_name: str) -> float:
        """
        Calculate success rate for an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Success rate (0.0 to 1.0)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT
                    SUM(success_count) as total_success,
                    SUM(activation_count) as total_activations
                FROM node_connections
                WHERE origin_node = ?
            """,
                (agent_name,),
            )
            result = cursor.fetchone()

            if result and result[1] and result[1] > 0:
                return result[0] / result[1]
            return 0.0

    def get_all_connections(self, min_weight: float = 0) -> List[dict]:
        """
        Get all connections above a minimum weight threshold.

        Args:
            min_weight: Minimum weight to include

        Returns:
            List of connection dictionaries
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM node_connections
                WHERE weight >= ?
                ORDER BY weight DESC
            """,
                (min_weight,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def prune_weak_connections(self, threshold: float = 0) -> int:
        """
        Remove connections below a weight threshold (apoptosis).

        Args:
            threshold: Weight threshold for pruning

        Returns:
            Number of connections pruned
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                DELETE FROM node_connections
                WHERE weight <= ?
            """,
                (threshold,),
            )
            conn.commit()
            pruned_count = cursor.rowcount

        if pruned_count > 0:
            logger.info(
                f"Hebbian: Pruned {pruned_count} weak connections (threshold: {threshold})"
            )

        return pruned_count

    def reset_weights(self):
        """Reset all weights (for testing/debugging).

        Returns:
            None: This function does not return a value.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM node_connections")
            conn.execute("DELETE FROM agent_pair_weights")
            conn.execute("DELETE FROM agent_timing_samples")
            conn.execute("DELETE FROM agent_timing_metrics")
            conn.execute("DELETE FROM hebbian_learning_events")
            conn.execute(
                "UPDATE hebbian_engine_state SET last_agent = NULL, "
                "last_performance = NULL, updated_at = NULL WHERE singleton = 1"
            )
            conn.commit()
        logger.warning("Hebbian: All weights reset!")

    def get_network_summary(self) -> dict:
        """
        Get summary statistics for the entire Hebbian network.

        Returns:
            Dictionary with network statistics
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total_connections,
                    AVG(weight) as avg_weight,
                    MAX(weight) as max_weight,
                    SUM(activation_count) as total_activations,
                    SUM(success_count) as total_successes,
                    SUM(failure_count) as total_failures
                FROM node_connections
            """)
            result = cursor.fetchone()

            if result:
                summary = {
                    "total_connections": result[0],
                    "average_weight": result[1] or 0.0,
                    "max_weight": result[2] or 0.0,
                    "total_activations": result[3] or 0,
                    "total_successes": result[4] or 0,
                    "total_failures": result[5] or 0,
                    "success_rate": (
                        result[4] / result[3] if result[3] and result[3] > 0 else 0.0
                    ),
                }
                summary.update(self.get_compounding_value())
                return summary
            return {}

    def export_snapshot(self) -> dict:
        """Return all Hebbian-owned tables as a JSON-serializable snapshot."""
        tables = (
            "node_connections",
            "agent_pair_weights",
            "agent_timing_samples",
            "agent_timing_metrics",
            "hebbian_engine_state",
            "hebbian_learning_events",
        )
        snapshot = {"schema_version": 1, "tables": {}}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            for table in tables:
                snapshot["tables"][table] = [
                    dict(row) for row in conn.execute(f"SELECT * FROM {table}")
                ]
        return snapshot

    def restore_snapshot(self, snapshot: dict) -> dict:
        """Atomically restore a snapshot produced by :meth:`export_snapshot`."""
        expected_tables = (
            "node_connections",
            "agent_pair_weights",
            "agent_timing_samples",
            "agent_timing_metrics",
            "hebbian_engine_state",
            "hebbian_learning_events",
        )
        tables = snapshot.get("tables") if isinstance(snapshot, dict) else None
        if not isinstance(tables, dict):
            raise ValueError("Hebbian snapshot must contain a tables object")

        restored = {}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            for table in reversed(expected_tables):
                conn.execute(f"DELETE FROM {table}")
            for table in expected_tables:
                rows = tables.get(table, [])
                if not isinstance(rows, list):
                    raise ValueError(f"Hebbian table {table!r} must be a list")
                columns = [
                    row[1] for row in conn.execute(f"PRAGMA table_info({table})")
                ]
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError(
                            f"Hebbian table {table!r} rows must be objects"
                        )
                    unknown = set(row) - set(columns)
                    if unknown:
                        raise ValueError(
                            f"Hebbian table {table!r} has unknown columns: "
                            f"{sorted(unknown)}"
                        )
                    selected = [column for column in columns if column in row]
                    placeholders = ", ".join("?" for _ in selected)
                    conn.execute(
                        f"INSERT INTO {table} ({', '.join(selected)}) "
                        f"VALUES ({placeholders})",
                        [row[column] for column in selected],
                    )
                restored[table] = len(rows)
            if not tables.get("hebbian_engine_state"):
                conn.execute(
                    "INSERT INTO hebbian_engine_state "
                    "(singleton, last_agent, last_performance, updated_at) "
                    "VALUES (1, NULL, NULL, NULL)"
                )
            conn.commit()
        return restored

    def get_connections_list(self, limit: int = 50) -> List[dict]:
        """
        Get top connections sorted by weight for web UI display.

        Args:
            limit: Maximum number of connections to return

        Returns:
            List of connection dictionaries with computed success rates
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT origin_node, target_node, weight, activation_count,
                       success_count, failure_count
                FROM node_connections
                ORDER BY weight DESC
                LIMIT ?
                """,
                (limit,),
            )

            connections = []
            for row in cursor.fetchall():
                conn_dict = dict(row)
                # Compute success rate
                if conn_dict["activation_count"] > 0:
                    conn_dict["success_rate"] = (
                        conn_dict["success_count"] / conn_dict["activation_count"]
                    )
                else:
                    conn_dict["success_rate"] = 0.0
                connections.append(conn_dict)

            return connections
