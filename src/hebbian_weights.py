"""
Hebbian Learning Layer for Artemis City
Implements simple w = +1 / w = -1 connection weighting for agent-task relationships.

"Cells that fire together wire together" - applied to agent orchestration.
"""

import sqlite3
import os
import time
from datetime import datetime
from typing import Optional, List, Tuple
from ..utils.helpers import logger

# Lazy import to avoid circular dependency
_run_logger = None


def _get_run_logger():
    """Lazy load run logger to avoid circular imports."""
    global _run_logger
    if _run_logger is None:
        try:
            from ..utils.run_logger import get_run_logger

            _run_logger = get_run_logger()
        except Exception:
            _run_logger = None
    return _run_logger


class HebbianWeightManager:
    """
    Manages connection weights between nodes (agents, tasks, outputs) using Hebbian learning.

    Simple update rule:
    - Successful activation: ΔW = +1
    - Failed activation: ΔW = -1
    - Weight threshold for pruning: configurable
    """

    def __init__(self, db_path: str = "data/hebbian_weights.db"):
        """
        Initialize Hebbian weight manager with SQLite backend.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_db_directory()
        self._initialize_database()
        logger.info(f"HebbianWeightManager initialized with database: {db_path}")

    def _ensure_db_directory(self):
        """Ensure the data directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"Created directory for Hebbian weights: {db_dir}")

    def _initialize_database(self):
        """Create the node_connections table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
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
            """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_origin
                ON node_connections(origin_node)
            """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_weight
                ON node_connections(weight DESC)
            """
            )
            conn.commit()

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
        """Reset all weights (for testing/debugging)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM node_connections")
            conn.commit()
        logger.warning("Hebbian: All weights reset!")

    def get_network_summary(self) -> dict:
        """
        Get summary statistics for the entire Hebbian network.

        Returns:
            Dictionary with network statistics
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total_connections,
                    AVG(weight) as avg_weight,
                    MAX(weight) as max_weight,
                    SUM(activation_count) as total_activations,
                    SUM(success_count) as total_successes,
                    SUM(failure_count) as total_failures
                FROM node_connections
            """
            )
            result = cursor.fetchone()

            if result:
                return {
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

            return {}

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
                (limit,)
            )

            connections = []
            for row in cursor.fetchall():
                conn_dict = dict(row)
                # Compute success rate
                if conn_dict['activation_count'] > 0:
                    conn_dict['success_rate'] = conn_dict['success_count'] / conn_dict['activation_count']
                else:
                    conn_dict['success_rate'] = 0.0
                connections.append(conn_dict)

            return connections
