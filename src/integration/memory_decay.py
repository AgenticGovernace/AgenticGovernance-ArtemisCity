"""Memory decay & retention service.

Implements the "Memory Decay & Retention Policy" described in the Artemis City
whitebook / ``docs/GOVERNANCE.md``:

* **Decay**     — an unused node loses ``decay_rate`` of its weight for every
  ``decay_interval_days`` (default 30) it has gone without access.
* **Archival**  — a node unused for ``archive_threshold_days`` (default 180) is
  flagged read-only (``archived = True``) and excluded from further decay.
* **Deletion**  — once a node's weight falls below ``delete_threshold_weight``
  (default 0.01) it is removed from the working set.
* **Restoration** — accessing an archived node un-archives it and applies a
  ``restore_boost`` (default +10%), per the whitebook's restoration hooks.

Every weight change is emitted as a JSONL provenance event matching the schema
in the whitebook ("event": "memory_decay", previous/new weight, reason, ...).

Design notes
------------
The service is deliberately **self-contained**: it operates on in-memory
:class:`MemoryNode` objects registered via :meth:`MemoryDecayService.register_node`.
This is exactly the contract exercised by ``benchmarks/bench_memory_ops.py`` and
keeps the module trivially unit-testable. An optional ``sink`` callback lets a
caller mirror weight changes into a real backing store (e.g. the vector store's
saliency metadata) without coupling this module to it.

Import tolerance
----------------
The module works whether imported as ``src.integration.memory_decay`` (repo root
on ``sys.path`` — tests and app) or as ``integration.memory_decay`` (``src/`` on
``sys.path`` — the benchmark). The shared logger is resolved accordingly with a
standard-logging fallback so the module never fails to import.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:  # repo root on path (tests / app): `src` is a package
    from src.runtime_paths import log_path as resolve_log_path
    from src.utils.helpers import logger
except ImportError:  # pragma: no cover - exercised under benchmark/bare layouts
    try:  # src/ itself on path (benchmark): `utils` is top-level
        from runtime_paths import log_path as resolve_log_path
        from utils.helpers import logger
    except ImportError:  # last resort: never fail to import over logging
        import logging

        logger = logging.getLogger("artemis.memory_decay")


# Sink receives (node, previous_weight, new_weight) on every applied change.
WeightChangeSink = Callable[["MemoryNode", float, float], None]


def _now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


@dataclass
class MemoryNode:
    """A single unit of memory subject to decay.

    Attributes:
        node_id: Stable identifier for the node.
        content: The node's payload (kept for provenance / sink use).
        weight: Current saliency weight in ``[0.0, ...]``; decays toward 0.
        last_access: Timestamp of the most recent access. Defaults to now.
        archived: True once the node has been archived (read-only).
        created_at: Creation timestamp (informational).
    """

    node_id: str
    content: str
    weight: float
    last_access: datetime = field(default_factory=_now)
    archived: bool = False
    created_at: datetime = field(default_factory=_now)


@dataclass
class DecayCycleResult:
    """Summary of a single :meth:`MemoryDecayService.run_decay_cycle` pass.

    Attributes:
        scanned: Number of nodes inspected.
        decayed: Number of nodes whose weight was reduced.
        archived: Number of nodes newly archived this cycle.
        deleted: Number of nodes removed this cycle.
        events: Provenance event dicts generated this cycle.
    """

    scanned: int = 0
    decayed: int = 0
    archived: int = 0
    deleted: int = 0
    events: list[dict] = field(default_factory=list)


class MemoryDecayService:
    """Apply time-based decay, archival, and deletion to registered memory nodes."""

    def __init__(
        self,
        decay_rate: float = 0.05,
        archive_threshold_days: int = 180,
        delete_threshold_weight: float = 0.01,
        decay_interval_days: int = 30,
        restore_boost: float = 0.10,
        log_dir: str | None = None,
        enable_provenance: bool = True,
        sink: WeightChangeSink | None = None,
    ) -> None:
        """Initialize the decay service.

        Args:
            decay_rate: Fraction of weight removed per ``decay_interval_days``
                of inactivity (e.g. 0.05 = 5% per 30 days).
            archive_threshold_days: Days of inactivity after which a node is
                archived (made read-only).
            delete_threshold_weight: Weight below which a node is deleted.
            decay_interval_days: Length in days of one decay period.
            restore_boost: Fractional weight boost applied on restoration.
            log_dir: Directory for JSONL provenance logs.
            enable_provenance: When False, no provenance files are written.
            sink: Optional callback invoked as ``sink(node, prev, new)`` on each
                applied weight change, for mirroring into a backing store.
        """
        if decay_interval_days <= 0:
            raise ValueError("decay_interval_days must be positive")
        self.decay_rate = decay_rate
        self.archive_threshold_days = archive_threshold_days
        self.delete_threshold_weight = delete_threshold_weight
        self.decay_interval_days = decay_interval_days
        self.restore_boost = restore_boost
        self.log_dir = Path(
            resolve_log_path(
                "memory_decay",
                log_dir,
                env_var="ARTEMIS_MEMORY_DECAY_LOG_DIR",
            )
        )
        self.enable_provenance = enable_provenance
        self.sink = sink
        self.nodes: dict[str, MemoryNode] = {}

    # ------------------------------------------------------------------
    # Registration / access
    # ------------------------------------------------------------------

    def register_node(self, node: MemoryNode) -> MemoryNode:
        """Register (or replace) a node in the working set.

        Args:
            node: The :class:`MemoryNode` to track.

        Returns:
            The registered node.
        """
        self.nodes[node.node_id] = node
        return node

    def register_nodes(self, nodes) -> int:
        """Register many nodes at once.

        Args:
            nodes: Iterable of :class:`MemoryNode`.

        Returns:
            The number of nodes registered.
        """
        count = 0
        for node in nodes:
            self.register_node(node)
            count += 1
        return count

    def get_node(self, node_id: str) -> MemoryNode | None:
        """Return a registered node by id, or None."""
        return self.nodes.get(node_id)

    def all_nodes(self) -> list[MemoryNode]:
        """Return all currently registered nodes."""
        return list(self.nodes.values())

    def record_access(
        self, node_id: str, now: datetime | None = None
    ) -> MemoryNode | None:
        """Mark a node as accessed (resets its decay clock).

        Args:
            node_id: Id of the node being accessed.
            now: Optional timestamp to record (defaults to current UTC time).

        Returns:
            The node, or None if it is not registered.
        """
        node = self.nodes.get(node_id)
        if node is None:
            return None
        node.last_access = now or _now()
        return node

    def restore_node(
        self, node_id: str, now: datetime | None = None
    ) -> MemoryNode | None:
        """Un-archive a node and apply the restoration weight boost.

        Args:
            node_id: Id of the node to restore.
            now: Optional timestamp recorded as the access time.

        Returns:
            The restored node, or None if it is not registered.
        """
        node = self.nodes.get(node_id)
        if node is None:
            return None
        previous = node.weight
        node.archived = False
        node.weight = node.weight * (1.0 + self.restore_boost)
        node.last_access = now or _now()
        self._emit(
            self._event("memory_restore", node, previous, node.weight, "restored")
        )
        if self.sink is not None:
            self._safe_sink(node, previous, node.weight)
        return node

    # ------------------------------------------------------------------
    # Decay cycle
    # ------------------------------------------------------------------

    def run_decay_cycle(self, now: datetime | None = None) -> DecayCycleResult:
        """Run one decay/archival/deletion pass over all registered nodes.

        Args:
            now: Optional reference time (defaults to current UTC time). Useful
                for deterministic testing.

        Returns:
            A :class:`DecayCycleResult` summarizing the pass.
        """
        now = now or _now()
        result = DecayCycleResult()
        to_delete: list[str] = []

        for node in list(self.nodes.values()):
            result.scanned += 1
            if node.archived:
                continue  # archived nodes are read-only; excluded from decay

            days_unused = self._days_unused(node, now)
            if days_unused < self.decay_interval_days:
                continue

            periods = days_unused // self.decay_interval_days
            reduction = self.decay_rate * periods
            previous = node.weight
            new_weight = max(0.0, node.weight - reduction)

            if new_weight != previous:
                node.weight = new_weight
                result.decayed += 1
                result.events.append(
                    self._event(
                        "memory_decay",
                        node,
                        previous,
                        new_weight,
                        f"unused_{days_unused}_days",
                    )
                )
                if self.sink is not None:
                    self._safe_sink(node, previous, new_weight)

            # Deletion takes precedence over archival.
            if new_weight < self.delete_threshold_weight:
                to_delete.append(node.node_id)
                result.deleted += 1
                result.events.append(
                    self._event(
                        "memory_delete",
                        node,
                        previous,
                        new_weight,
                        f"weight_below_{self.delete_threshold_weight}",
                    )
                )
            elif days_unused >= self.archive_threshold_days:
                node.archived = True
                result.archived += 1
                result.events.append(
                    self._event(
                        "memory_archive",
                        node,
                        previous,
                        new_weight,
                        f"unused_{days_unused}_days",
                    )
                )

        for node_id in to_delete:
            self.nodes.pop(node_id, None)

        if result.events and self.enable_provenance:
            self._write_provenance(result.events, now)

        if result.decayed or result.archived or result.deleted:
            logger.info(
                "Memory decay cycle: scanned=%d decayed=%d archived=%d deleted=%d",
                result.scanned,
                result.decayed,
                result.archived,
                result.deleted,
            )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _days_unused(self, node: MemoryNode, now: datetime) -> int:
        """Whole days since the node was last accessed (naive datetimes -> UTC)."""
        last = node.last_access
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        delta = now - last
        return max(0, delta.days)

    def _event(
        self,
        event: str,
        node: MemoryNode,
        previous_weight: float,
        new_weight: float,
        reason: str,
    ) -> dict:
        """Build a provenance event dict matching the whitebook schema."""
        last = node.last_access
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return {
            "event": event,
            "timestamp": _now().isoformat(),
            "node_id": node.node_id,
            "previous_weight": previous_weight,
            "new_weight": new_weight,
            "reason": reason,
            "last_access": last.isoformat(),
        }

    def _emit(self, event: dict) -> None:
        """Write a single provenance event (best-effort)."""
        if self.enable_provenance:
            self._write_provenance([event], _now())

    def _safe_sink(self, node: MemoryNode, previous: float, new_weight: float) -> None:
        """Invoke the sink callback without letting failures break a cycle."""
        if self.sink is None:
            return
        try:
            self.sink(node, previous, new_weight)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Memory decay sink failed for node %s", node.node_id)

    def _write_provenance(self, events: list[dict], now: datetime) -> None:
        """Append events to ``log_dir/<date>.jsonl`` (best-effort)."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.log_dir / f"{now.date().isoformat()}.jsonl"
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.writelines(json.dumps(event) + "\n" for event in events)
        except OSError:  # pragma: no cover - provenance is non-critical
            logger.warning("Could not write memory decay provenance log", exc_info=True)
