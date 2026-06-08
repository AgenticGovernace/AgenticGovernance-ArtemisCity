from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Levels & thresholds
# ---------------------------------------------------------------------------


class TrustLevel(Enum):
    """Trust level categories."""

    FULL = "full"  # Unrestricted access
    HIGH = "high"  # Most operations allowed
    MEDIUM = "medium"  # Limited operations
    LOW = "low"  # Read-only
    UNTRUSTED = "untrusted"  # No access


# Canonical score → level thresholds. A score `s` belongs to the highest
# level whose threshold it meets, i.e. `s >= TRUST_THRESHOLDS[level]`.
TRUST_THRESHOLDS: Dict[TrustLevel, float] = {
    TrustLevel.FULL: 0.9,
    TrustLevel.HIGH: 0.7,
    TrustLevel.MEDIUM: 0.5,
    TrustLevel.LOW: 0.3,
    TrustLevel.UNTRUSTED: 0.0,
}

_LEVELS_DESC: Tuple[TrustLevel, ...] = (
    TrustLevel.FULL,
    TrustLevel.HIGH,
    TrustLevel.MEDIUM,
    TrustLevel.LOW,
    TrustLevel.UNTRUSTED,
)


def _score_to_level(score: float) -> TrustLevel:
    """Map a numeric score to its trust level using ``TRUST_THRESHOLDS``."""
    for level in _LEVELS_DESC:
        if score >= TRUST_THRESHOLDS[level]:
            return level
    return TrustLevel.UNTRUSTED


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp.

    Matches the convention used by ``src/integration/agent_registry.py`` so
    timestamps remain comparable across stores.
    """
    return datetime.now(timezone.utc)


def _coerce_aware(value: datetime) -> datetime:
    """Normalize a possibly naive datetime to UTC-aware.

    Naive datetimes returned from SQLite (or supplied by older callers) are
    assumed to already be in UTC. This is safer than silently mixing zones.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# TrustScore
# ---------------------------------------------------------------------------


@dataclass
class TrustScore:
    """Trust score for an entity (agent, memory, protocol)."""

    entity_id: str
    entity_type: str
    score: float
    level: TrustLevel
    last_updated: datetime = field(default_factory=_utcnow)
    decay_rate: float = 0.01  # 1% per day default
    reinforcement_events: int = 0
    penalty_events: int = 0

    def apply_decay(self, *, now: Optional[datetime] = None) -> float:
        """Apply natural decay based on elapsed time since ``last_updated``.

        Continuous in elapsed time (fractional days), floored at the
        threshold of the score's *current* category so passive decay can
        never demote a tier — that requires an explicit penalty event.
        Mutates ``self.score`` and advances ``self.last_updated`` so
        repeated reads within the same instant are idempotent.
        """
        now = _coerce_aware(now or _utcnow())
        self.last_updated = _coerce_aware(self.last_updated)
        elapsed = (now - self.last_updated).total_seconds()
        # Guard against clock skew / future timestamps.
        days_elapsed = max(0.0, elapsed / 86_400.0)
        if days_elapsed == 0.0:
            return self.score

        decayed = self.score * (1.0 - self.decay_rate) ** days_elapsed
        floor = TRUST_THRESHOLDS.get(self.level, 0.0)
        self.score = max(decayed, floor)
        self.last_updated = now
        self._update_level()
        return self.score

    def reinforce(self, amount: float = 0.02) -> float:
        """Reinforce trust score after a successful action (+0.02 default)."""
        self.score = min(1.0, self.score + amount)
        self.reinforcement_events += 1
        self.last_updated = _utcnow()
        self._update_level()
        return self.score

    def penalize(self, amount: float = 0.05) -> float:
        """Penalize trust score after a failed action (-0.05 default)."""
        self.score = max(0.0, self.score - amount)
        self.penalty_events += 1
        self.last_updated = _utcnow()
        self._update_level()
        return self.score

    def _update_level(self) -> None:
        self.level = _score_to_level(self.score)

    # ---- (de)serialization ------------------------------------------------

    def to_dict(self) -> Dict:
        """Serialize for storage / API responses (ISO-8601 UTC)."""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "score": self.score,
            "level": self.level.value,
            "last_updated": _coerce_aware(self.last_updated).isoformat(),
            "decay_rate": self.decay_rate,
            "reinforcement_events": self.reinforcement_events,
            "penalty_events": self.penalty_events,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "TrustScore":
        """Reconstruct a TrustScore from a DB row produced by ``TrustStore``."""
        return cls(
            entity_id=row["entity_id"],
            entity_type=row["entity_type"],
            score=float(row["score"]),
            level=TrustLevel(row["level"]),
            last_updated=_coerce_aware(datetime.fromisoformat(row["last_updated"])),
            decay_rate=float(row["decay_rate"]),
            reinforcement_events=int(row["reinforcement_events"]),
            penalty_events=int(row["penalty_events"]),
        )


# ---------------------------------------------------------------------------
# Persistent store
# ---------------------------------------------------------------------------


def _default_db_path() -> Path:
    """Resolve the default trust store path.

    Honors ``ARTEMIS_TRUST_DB`` so tests / containers can redirect storage.
    """
    env = os.environ.get("ARTEMIS_TRUST_DB")
    if env:
        return Path(env)
    # Sit beside the agent registry by default.
    return Path("data/trust_scores.db")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trust_scores (
    entity_type           TEXT NOT NULL,
    entity_id             TEXT NOT NULL,
    score                 REAL NOT NULL,
    level                 TEXT NOT NULL,
    last_updated          TEXT NOT NULL,
    decay_rate            REAL NOT NULL DEFAULT 0.01,
    reinforcement_events  INTEGER NOT NULL DEFAULT 0,
    penalty_events        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_type, entity_id)
);
"""


class TrustStore:
    """Thin SQLite-backed persistence layer for :class:`TrustScore`."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def db_path(self) -> Path:
        return self._db_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def load_all(self) -> Dict[str, TrustScore]:
        """Return all persisted scores keyed by ``entity_type:entity_id``."""
        out: Dict[str, TrustScore] = {}
        with self._lock, self._connect() as conn:
            for row in conn.execute("SELECT * FROM trust_scores"):
                score = TrustScore.from_row(row)
                out[f"{score.entity_type}:{score.entity_id}"] = score
        return out

    def upsert(self, score: TrustScore) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trust_scores (
                    entity_type, entity_id, score, level, last_updated,
                    decay_rate, reinforcement_events, penalty_events
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                    score = excluded.score,
                    level = excluded.level,
                    last_updated = excluded.last_updated,
                    decay_rate = excluded.decay_rate,
                    reinforcement_events = excluded.reinforcement_events,
                    penalty_events = excluded.penalty_events
                """,
                (
                    score.entity_type,
                    score.entity_id,
                    score.score,
                    score.level.value,
                    _coerce_aware(score.last_updated).isoformat(),
                    score.decay_rate,
                    score.reinforcement_events,
                    score.penalty_events,
                ),
            )


# ---------------------------------------------------------------------------
# TrustInterface
# ---------------------------------------------------------------------------


class TrustInterface:
    """Interface for trust-aware memory operations.

    Manages trust scores for agents and determines access permissions for
    memory operations based on trust levels. Mirrors the TypeScript
    ``TrustController`` so both surfaces agree on operations per level.
    """

    DEFAULT_AGENT_TRUST = 0.8
    DEFAULT_MEMORY_TRUST = 0.7

    # Kept in sync with TRUST_OPERATIONS in
    # app/api/controllers/trustController.ts.
    OPERATION_PERMISSIONS: Dict[TrustLevel, List[str]] = {
        TrustLevel.FULL: [
            "read",
            "write",
            "delete",
            "search",
            "tag",
            "update",
            "frontmatter",
        ],
        TrustLevel.HIGH: [
            "read",
            "write",
            "search",
            "tag",
            "update",
            "frontmatter",
        ],
        TrustLevel.MEDIUM: ["read", "write", "search", "tag"],
        TrustLevel.LOW: ["read", "search"],
        TrustLevel.UNTRUSTED: [],
    }

    def __init__(
        self,
        *,
        store: Optional[TrustStore] = None,
        db_path: Optional[Path] = None,
    ) -> None:
        """Initialize trust interface.

        Args:
            store: Pre-built :class:`TrustStore` (useful for injection in tests).
            db_path: Override the SQLite path; ignored if ``store`` is provided.
        """
        self._store = store if store is not None else TrustStore(db_path)
        self.trust_scores: Dict[str, TrustScore] = self._store.load_all()
        # Seed only the entries that aren't already persisted.
        self._initialize_default_agents()

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _key(entity_id: str, entity_type: str) -> str:
        return f"{entity_type}:{entity_id}"

    def _persist(self, score: TrustScore) -> None:
        self._store.upsert(score)

    def _initialize_default_agents(self) -> None:
        core_agents = {
            "artemis": 0.95,
            "pack_rat": 0.85,
            "daemon": 0.85,
            "copilot": 0.80,
        }
        for agent_id, score in core_agents.items():
            key = self._key(agent_id, "agent")
            if key in self.trust_scores:
                continue  # respect previously-persisted state
            trust_score = TrustScore(
                entity_id=agent_id,
                entity_type="agent",
                score=score,
                level=_score_to_level(score),
                last_updated=_utcnow(),
            )
            self.trust_scores[key] = trust_score
            self._persist(trust_score)

    # ---- public API -------------------------------------------------------

    def get_trust_score(self, entity_id: str, entity_type: str = "agent") -> TrustScore:
        """Get the trust score for an entity, creating one if absent.

        Always applies decay before returning so callers see a value that
        reflects elapsed time since the last update, and persists any
        change so the next process restart picks up where we left off.
        """
        key = self._key(entity_id, entity_type)
        trust_score = self.trust_scores.get(key)
        if trust_score is None:
            default_score = (
                self.DEFAULT_AGENT_TRUST
                if entity_type == "agent"
                else self.DEFAULT_MEMORY_TRUST
            )
            trust_score = TrustScore(
                entity_id=entity_id,
                entity_type=entity_type,
                score=default_score,
                level=_score_to_level(default_score),
                last_updated=_utcnow(),
            )
            self.trust_scores[key] = trust_score
            self._persist(trust_score)
            return trust_score

        prev_score = trust_score.score
        prev_last_updated = trust_score.last_updated
        trust_score.apply_decay()
        # Only hit SQLite when something actually changed.
        if (
            trust_score.score != prev_score
            or trust_score.last_updated != prev_last_updated
        ):
            self._persist(trust_score)
        return trust_score

    def can_perform_operation(
        self, entity_id: str, operation: str, entity_type: str = "agent"
    ) -> bool:
        trust_score = self.get_trust_score(entity_id, entity_type)
        return operation in self.OPERATION_PERMISSIONS.get(trust_score.level, [])

    def record_success(
        self, entity_id: str, entity_type: str = "agent", amount: float = 0.02
    ) -> float:
        trust_score = self.get_trust_score(entity_id, entity_type)
        new_score = trust_score.reinforce(amount)
        self._persist(trust_score)
        return new_score

    def record_failure(
        self, entity_id: str, entity_type: str = "agent", amount: float = 0.05
    ) -> float:
        trust_score = self.get_trust_score(entity_id, entity_type)
        new_score = trust_score.penalize(amount)
        self._persist(trust_score)
        return new_score

    def get_trust_report(self) -> Dict:
        by_level: Dict[str, List[Dict]] = {}
        for trust_score in self.trust_scores.values():
            by_level.setdefault(trust_score.level.value, []).append(
                {
                    "id": trust_score.entity_id,
                    "type": trust_score.entity_type,
                    "score": round(trust_score.score, 3),
                    "reinforcements": trust_score.reinforcement_events,
                    "penalties": trust_score.penalty_events,
                }
            )
        return {
            "total_entities": len(self.trust_scores),
            "by_level": by_level,
            "timestamp": _utcnow().isoformat(),
        }

    def filter_by_trust(
        self,
        items: List[Dict],
        min_trust_level: TrustLevel = TrustLevel.MEDIUM,
    ) -> List[Dict]:
        min_score = TRUST_THRESHOLDS[min_trust_level]
        filtered: List[Dict] = []
        for item in items:
            entity_id = item.get("entity_id")
            if not entity_id:
                continue
            entity_type = item.get("entity_type", "agent")
            trust_score = self.get_trust_score(entity_id, entity_type)
            if trust_score.score >= min_score:
                filtered.append(item)
        return filtered


# ---------------------------------------------------------------------------
# Global accessor
# ---------------------------------------------------------------------------


_global_trust_interface: Optional[TrustInterface] = None
_global_lock = threading.Lock()


def get_trust_interface() -> TrustInterface:
    """Get or create the global :class:`TrustInterface` instance."""
    global _global_trust_interface
    if _global_trust_interface is None:
        with _global_lock:
            if _global_trust_interface is None:
                _global_trust_interface = TrustInterface()
    return _global_trust_interface


def reset_trust_interface_for_tests() -> None:
    """Clear the global singleton (intended for tests only)."""
    global _global_trust_interface
    with _global_lock:
        _global_trust_interface = None
