"""Write-through coordination for learning and governance state.

The registry owns execution history, violations, and the trust formula.  The
standalone trust database is a durable projection used by API and permission
consumers, while the Hebbian database owns learned connections.  This module
keeps those stores synchronized without applying a trust penalty a second time
or treating a governance-only violation as task-performance evidence.
"""

from __future__ import annotations

from src.governance.trust import TrustMetrics, compute_trust_score
from src.utils.helpers import logger


class LearningGovernanceCoordinator:
    """Coordinate write-through mutations across registry, trust, and Hebbian stores."""

    def __init__(
        self,
        registry,
        trust_interface=None,
        hebbian_manager=None,
        checkpoint_store=None,
    ) -> None:
        self.registry = registry
        self.trust_interface = trust_interface
        self.hebbian_manager = hebbian_manager
        self.checkpoint_store = checkpoint_store

    @property
    def store(self):
        """Return the registry persistence object for facade or store callers."""
        return getattr(self.registry, "store", self.registry)

    def _agent_exists(self, agent_name: str) -> bool:
        return self.store.get_agent_record(agent_name) is not None

    def _registry_state(self, agent_name: str) -> dict | None:
        getter = getattr(self.registry, "get_governance_state", None)
        if callable(getter):
            return getter(agent_name)
        return self.store.get_governance_state(agent_name)

    def _set_registry_score(self, agent_name: str, score: float) -> None:
        if not self._agent_exists(agent_name):
            return
        setter = getattr(self.registry, "set_trust_score", None)
        if callable(setter):
            setter(agent_name, score)
        else:
            self.store.set_trust_score(agent_name, score)

    def mirror_trust_score(
        self,
        agent_name: str,
        score: float,
        *,
        success: bool | None = None,
        update_registry: bool = False,
    ) -> float:
        """Mirror one authoritative score without applying another adjustment."""
        normalized = max(0.0, min(1.0, float(score)))
        if update_registry:
            self._set_registry_score(agent_name, normalized)
        if self.trust_interface is not None:
            self.trust_interface.set_authoritative_score(
                agent_name,
                normalized,
                success=success,
            )
        return normalized

    def record_execution_outcome(
        self, agent_name: str, *, success: bool, learning: dict
    ) -> dict:
        """Persist one execution's registry mirror and trust projection."""
        result = self.registry.record_learning_outcome(
            agent_name,
            success=success,
            learning=learning,
        )
        self.mirror_trust_score(
            agent_name,
            result["trust_score"],
            success=success,
        )
        return result

    def record_violation(
        self, agent_name: str, violation_type: str, details: dict
    ) -> dict:
        """Record a governance violation and mirror its recalculated trust."""
        self.create_checkpoint(f"before_violation:{agent_name}")
        result = self.registry.record_violation(agent_name, violation_type, details)
        self.mirror_trust_score(agent_name, result["trust_score"])
        return result

    def clear_violations(
        self,
        agent_name: str,
        rationale: str,
        override_tier: str | None = None,
    ) -> int:
        """Clear violations and mirror the recalculated clean-state trust."""
        self.create_checkpoint(f"before_clear_violations:{agent_name}")
        cleared = self.registry.clear_violations(
            agent_name,
            rationale,
            override_tier,
        )
        state = self._registry_state(agent_name) or {}
        if state.get("trust_score") is not None:
            self.mirror_trust_score(agent_name, state["trust_score"])
        return cleared

    def set_trust_score(
        self,
        entity_id: str,
        score: float,
        *,
        entity_type: str = "agent",
    ):
        """Set a trust score and mirror agent entities into the registry."""
        if self.trust_interface is None:
            raise RuntimeError("trust persistence is unavailable")
        self.create_checkpoint(f"before_trust_set:{entity_type}:{entity_id}")
        normalized = max(0.0, min(1.0, float(score)))
        updated = self.trust_interface.set_authoritative_score(
            entity_id,
            normalized,
            entity_type=entity_type,
        )
        if entity_type == "agent":
            self._set_registry_score(entity_id, normalized)
        return updated

    def record_trust_adjustment(
        self,
        entity_id: str,
        *,
        success: bool,
        amount: float,
        entity_type: str = "agent",
    ):
        """Apply one explicit trust adjustment and mirror its resulting score."""
        if self.trust_interface is None:
            raise RuntimeError("trust persistence is unavailable")
        self.create_checkpoint(f"before_trust_adjustment:{entity_type}:{entity_id}")
        if success:
            self.trust_interface.record_success(entity_id, entity_type, amount)
        else:
            self.trust_interface.record_failure(entity_id, entity_type, amount)
        updated = self.trust_interface.get_trust_score(entity_id, entity_type)
        if entity_type == "agent":
            self._set_registry_score(entity_id, updated.score)
        return updated

    def apply_trust_decay(self, decay_rate: float | None = None) -> list[dict]:
        """Apply trust decay and mirror all registered agent projections."""
        if self.trust_interface is None:
            raise RuntimeError("trust persistence is unavailable")
        self.create_checkpoint("before_trust_decay")
        updated: list[dict] = []
        for score in list(self.trust_interface.trust_scores.values()):
            if decay_rate is not None:
                score.decay_rate = decay_rate
            score.apply_decay()
            self.trust_interface.persist(score)
            if score.entity_type == "agent":
                self._set_registry_score(score.entity_id, score.score)
            updated.append(score.to_dict())
        return updated

    def create_checkpoint(self, reason: str) -> dict | None:
        """Capture registry and Hebbian state before a consequential mutation."""
        if self.checkpoint_store is None:
            return None
        config_snapshot = {}
        if self.hebbian_manager is not None:
            config_snapshot["hebbian"] = self.hebbian_manager.export_snapshot()
        return self.checkpoint_store.create_checkpoint(
            self.store.export_snapshot(),
            checkpoint_type="manual",
            metadata={"reason": reason, "automatic": True},
            config_snapshot=config_snapshot,
        )

    def reconcile_agent(self, agent_name: str) -> float | None:
        """Repair the trust projection from the registry's authoritative value."""
        state = self._registry_state(agent_name)
        if not state:
            return None
        score = state.get("trust_score")
        if score is None:
            record = self.store.get_agent_record(agent_name) or {}
            score = compute_trust_score(
                TrustMetrics(
                    successful_executions=int(record.get("successful_executions") or 0),
                    total_executions=int(record.get("execution_count") or 0),
                    recent_violation_count=int(state.get("violation_count") or 0),
                )
            )
            self._set_registry_score(agent_name, score)
        score = self.mirror_trust_score(agent_name, score)
        logger.debug("Reconciled trust projection for %s", agent_name)
        return score

    def mirror_hebbian_summary(
        self, agent_name: str, task_type: str | None = None
    ) -> dict | None:
        """Refresh registry Hebbian fields after an administrative weight edit."""
        if self.hebbian_manager is None or not self._agent_exists(agent_name):
            return None
        learning = self.hebbian_manager.get_agent_learning_summary(
            agent_name,
            task_type=task_type,
        )
        updater = getattr(self.registry, "update_learning_snapshot", None)
        if callable(updater):
            updater(agent_name, learning)
        else:
            self.store.update_learning_snapshot(agent_name, learning)
        return learning
