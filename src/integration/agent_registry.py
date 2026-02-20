# src/integration/agent_registry.py

from dataclasses import dataclass
from typing import Dict, List
import json
import os
import sqlite3
import time
from agents.base_agent import BaseAgent
from utils.helpers import logger


@dataclass
class AgentScore:
    alignment: float  # 0.0-1.0 policy adherence
    accuracy: float  # 0.0-1.0 output quality
    efficiency: float  # 0.0-1.0 speed/cost metric

    @property
    def composite_score(self) -> float:
        """Weighted composite score"""
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
        """Create the agents table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
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
                """
            )
            conn.commit()

    def load_scores(self) -> Dict[str, AgentScore]:
        """Load persisted scores for all agents."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT name, alignment, accuracy, efficiency
                FROM agents
                """
            )
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

    def upsert_agent(self, agent: BaseAgent, default_score: AgentScore) -> AgentScore:
        """Insert agent metadata if new; return persisted or default score."""
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
        """Persist updated score for an agent."""
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


class AgentRegistry:
    def __init__(self, db_path: str = "data/agent_registry.db"):
        self.store = AgentRegistryStore(db_path=db_path)
        self.agents: Dict[str, BaseAgent] = {}
        self.scores: Dict[str, AgentScore] = self.store.load_scores()

    def register_agent(self, agent: BaseAgent):
        """Registers a new agent."""
        if agent.name in self.agents:
            logger.info(
                f"Agent '{agent.name}' already registered; skipping duplicate registration."
            )
            return
        default_score = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
        persisted_score = self.store.upsert_agent(agent, default_score)
        self.agents[agent.name] = agent
        self.scores[agent.name] = persisted_score

    def get_agent(self, agent_name: str) -> BaseAgent:
        return self.agents.get(agent_name)

    def route_task(self, task: dict) -> str:
        """Route task to highest-scoring capable agent"""
        required_capability = task.get("required_capability")
        if not required_capability:
            raise ValueError(
                "Task dictionary must contain a 'required_capability' key."
            )

        candidates = [
            agent.name
            for agent in self.agents.values()
            if required_capability in agent.capabilities
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
        """Update agent score dimension with decay"""
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
        return list(self.agents.values())

    def get_agent_names(self) -> List[str]:
        return list(self.agents.keys())

    def get_all_agents_with_scores(self) -> List[Dict]:
        """Return all agents with their capabilities and performance scores."""
        result = []
        for agent in self.agents.values():
            score = self.scores.get(agent.name, AgentScore(0.5, 0.5, 0.5))
            result.append({
                "name": agent.name,
                "capabilities": agent.capabilities,
                "alignment": score.alignment,
                "accuracy": score.accuracy,
                "efficiency": score.efficiency,
                "composite_score": score.composite_score,
            })
        return sorted(result, key=lambda x: x["composite_score"], reverse=True)
