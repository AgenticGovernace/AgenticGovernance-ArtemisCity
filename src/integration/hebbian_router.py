"""Hebbian-weighted task routing.

Biases agent selection by *learned* success, not just the static composite
score. Among the agents capable of a task (and not quarantined/suspended), the
router blends each agent's static composite score with its Hebbian average
connection weight::

    score(agent) = (1 - alpha) * composite(agent) + alpha * hebbian_norm(agent)

``hebbian_norm`` is the agent's average Hebbian weight normalised across the
current candidates to ``[0, 1]``. With no Hebbian history (cold start) every
candidate gets a neutral prior, so routing reduces to the composite-score
ranking the registry already uses. Then, as the orchestrator strengthens (+1) /
weakens (-1) agent->task connections after each run, proven performers are
increasingly preferred. This is the production wiring of the adaptive
agent-selection rule prototyped in the ML notebooks (the highest-weight agent
wins, weights move by +/-1 on success/failure).

``alpha`` in ``[0, 1]`` controls how much learned weight overrides the static
score: ``0`` = pure composite (legacy behaviour), ``1`` = pure Hebbian weight.

The router is deliberately defensive: any failure reading a weight or score is
treated as the neutral prior, so a missing or mocked Hebbian source never breaks
routing — it simply falls back to composite-only behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

try:  # repo root on path (tests / app)
    from src.utils.helpers import logger
except ImportError:  # pragma: no cover - benchmark/bare layouts
    try:
        from utils.helpers import logger  # type: ignore
    except ImportError:
        import logging

        logger = logging.getLogger("artemis.hebbian_router")

# Agents in these governance states are ineligible for routing.
_BLOCKED_STATUSES = ("quarantined", "suspended")

DEFAULT_ALPHA = 0.3
NEUTRAL_PRIOR = 0.5


@dataclass
class CandidateScore:
    """Per-candidate routing breakdown (useful for logging / observability)."""

    name: str
    composite: float
    hebbian_weight: float  # raw average Hebbian weight
    hebbian_norm: float  # normalised across candidates, [0, 1]
    blended: float


@dataclass
class RoutingDecision:
    """Result of a routing decision."""

    agent_name: str
    alpha: float
    candidates: List[CandidateScore] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize the decision (e.g. for the run logger / API).

        Returns:
            dict: Dictionary form of the decision and its candidate breakdown.
        """
        return {
            "agent_name": self.agent_name,
            "alpha": self.alpha,
            "candidates": [c.__dict__ for c in self.candidates],
        }


class HebbianRouter:
    """Select the best agent for a task by blending composite score + Hebbian weight."""

    def __init__(
        self,
        registry,
        hebbian,
        alpha: float = DEFAULT_ALPHA,
        neutral_prior: float = NEUTRAL_PRIOR,
    ) -> None:
        """Initialize the router.

        Args:
            registry: An ``AgentRegistry`` (read for capabilities, scores,
                governance state).
            hebbian: A ``HebbianWeightManager`` (read for average agent weight).
            alpha: Blend factor in ``[0, 1]``; higher means learned weight
                matters more relative to the static composite score.
            neutral_prior: Hebbian signal used when no history exists (cold
                start), so new agents are neither rewarded nor penalised.
        """
        self.registry = registry
        self.hebbian = hebbian
        self.alpha = max(0.0, min(1.0, float(alpha)))
        self.neutral_prior = neutral_prior

    def route(self, task: Dict[str, Any]) -> RoutingDecision:
        """Route a task to the highest blended-score capable agent.

        Args:
            task: Task dict; must contain ``required_capability``.

        Returns:
            RoutingDecision: The chosen agent plus the per-candidate breakdown.

        Raises:
            ValueError: If the task has no capability, or no eligible agent has it.
        """
        capability = task.get("required_capability")
        if not capability:
            raise ValueError(
                "Task dictionary must contain a 'required_capability' key."
            )

        candidates = [
            agent.name
            for agent in self.registry.get_all_agents()
            if capability in getattr(agent, "capabilities", [])
            and not self._is_blocked(agent.name)
        ]
        if not candidates:
            raise ValueError(
                f"No agent found with the required capability: {capability}"
            )

        raw = {
            name: (self._composite(name), self._hebbian_weight(name))
            for name in candidates
        }
        max_heb = max((heb for _, heb in raw.values()), default=0.0)

        scored: List[CandidateScore] = []
        for name in candidates:
            composite, heb_raw = raw[name]
            # Cold start (no weights anywhere) -> neutral prior for everyone, so
            # ranking collapses to the composite score.
            heb_norm = (heb_raw / max_heb) if max_heb > 0 else self.neutral_prior
            blended = (1.0 - self.alpha) * composite + self.alpha * heb_norm
            scored.append(CandidateScore(name, composite, heb_raw, heb_norm, blended))

        # Deterministic order: highest blended, then composite; name ascending
        # within ties (stable sort: sort by name first, then by the metrics).
        scored.sort(key=lambda c: c.name)
        scored.sort(key=lambda c: (c.blended, c.composite), reverse=True)
        best = scored[0]

        logger.info(
            "Hebbian routing (alpha=%.2f) -> %s "
            "(blended=%.3f, composite=%.3f, heb_weight=%.3f) over %d candidate(s)",
            self.alpha,
            best.name,
            best.blended,
            best.composite,
            best.hebbian_weight,
            len(scored),
        )
        return RoutingDecision(
            agent_name=best.name, alpha=self.alpha, candidates=scored
        )

    def route_name(self, task: Dict[str, Any]) -> str:
        """Convenience: route and return only the selected agent name."""
        return self.route(task).agent_name

    # ------------------------------------------------------------------
    # Internals (all defensive: never raise on a bad/mocked data source)
    # ------------------------------------------------------------------

    def _is_blocked(self, name: str) -> bool:
        """True if the agent is quarantined or suspended."""
        try:
            state = self.registry.get_governance_state(name)
            if state and state.get("status") in _BLOCKED_STATUSES:
                return True
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            return bool(self.registry.is_quarantined(name))
        except Exception:  # pragma: no cover - defensive
            return False

    def _composite(self, name: str) -> float:
        """Static composite score for an agent, or the neutral prior."""
        try:
            score = self.registry.scores.get(name)
            if score is None:
                return self.neutral_prior
            return float(score.composite_score)
        except Exception:  # pragma: no cover - defensive
            return self.neutral_prior

    def _hebbian_weight(self, name: str) -> float:
        """Average Hebbian weight for an agent; 0.0 if unavailable (cold start)."""
        try:
            return max(0.0, float(self.hebbian.get_agent_average_weight(name)))
        except Exception:  # mocked/missing source -> treat as no history
            return 0.0
