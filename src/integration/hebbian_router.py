"""Hebbian-weighted task routing.

Biases agent selection by *learned* success, not just the static composite
score. Among the agents capable of a task (and not quarantined/suspended, and
above the trust floor when one is configured), the router blends each agent's
static composite score with its Hebbian task-type connection weight and its
current trust score::

    score(agent) = (1 - alpha - beta) * composite(agent)
                 + alpha * hebbian_norm(agent)
                 + beta  * trust_score(agent)

``hebbian_norm`` is the simulation's effective signal — scoped individual
weight + rolling timing score + sequential pair bonus — normalized across the
current candidates to ``[0, 1]``. Legacy databases without scoped connections
fall back to the agent-wide average. With no learning history (cold start)
every candidate gets a neutral prior, so routing reduces to the composite-score
ranking the registry already uses.

``trust_score`` is the agent's current trust value in ``[0, 1]`` from
:class:`~src.integration.trust_interface.TrustInterface` (already decayed to
the moment of the routing decision). ``trust_floor`` is a hard cutoff: any
agent whose trust falls below it is excluded from candidacy, the same way
quarantined or suspended agents are. Floor exclusion happens *before* the
blend, so a sub-threshold agent cannot win regardless of Hebbian history.

``alpha`` and ``beta`` in ``[0, 1]`` with ``alpha + beta <= 1`` control how
much learned weight and trust override the static score. ``alpha=beta=0``
collapses routing back to the registry's composite-only behaviour.

``fallback_capability`` makes a general-purpose agent reachable: if no agent
advertises the requested capability (or the task omits one), the router retries
with the fallback capability (e.g. the LLM agent's ``llm_chat``) before giving
up. Leave it ``None`` to keep strict capability-matching (raise on no match).

The router is deliberately defensive: any failure reading a weight, score, or
trust value is treated as the neutral prior, so a missing or mocked source
never breaks routing — it simply falls back to whatever signals remain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:  # repo root on path (tests / app)
    from src.utils.helpers import logger
except ImportError:  # pragma: no cover - benchmark/bare layouts
    try:
        from utils.helpers import logger
    except ImportError:
        import logging

        logger = logging.getLogger("artemis.hebbian_router")

# Agents in these governance states are ineligible for routing.
_BLOCKED_STATUSES = ("quarantined", "suspended")

DEFAULT_ALPHA = 0.3
DEFAULT_BETA = 0.0
DEFAULT_TRUST_FLOOR = 0.0
NEUTRAL_PRIOR = 0.5
NEUTRAL_TRUST = 0.5


@dataclass
class CandidateScore:
    """Per-candidate routing breakdown (useful for logging / observability)."""

    name: str
    composite: float
    hebbian_weight: float  # raw average Hebbian weight
    hebbian_norm: float  # normalised across candidates, [0, 1]
    trust_score: float  # current trust in [0, 1] (already decay-adjusted)
    blended: float
    pair_bonus: float = 0.0
    timing_score: Optional[float] = None
    hebbian_effective: float = 0.0
    oscillation_rate: float = 0.0
    sentinel_alert: bool = False
    sentinel_samples: int = 0


@dataclass
class RoutingDecision:
    """Result of a routing decision."""

    agent_name: str
    alpha: float
    beta: float = 0.0
    trust_floor: float = 0.0
    candidates: List[CandidateScore] = field(default_factory=list)
    # The originally-requested capability, set when this decision came from the
    # fallback path (i.e. no agent had the requested capability). None otherwise.
    fallback_from: Optional[str] = None
    capability: Optional[str] = None
    routing_scope: Optional[str] = None
    atp_action_type: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize the decision (e.g. for the run logger / API).

        Returns:
            dict: Dictionary form of the decision and its candidate breakdown.
        """
        return {
            "agent_name": self.agent_name,
            "alpha": self.alpha,
            "beta": self.beta,
            "trust_floor": self.trust_floor,
            "fallback_from": self.fallback_from,
            "capability": self.capability,
            "routing_scope": self.routing_scope,
            "atp_action_type": self.atp_action_type,
            "candidates": [c.__dict__ for c in self.candidates],
        }


class HebbianRouter:
    """Select the best agent for a task by blending composite + Hebbian + trust."""

    def __init__(
        self,
        registry,
        hebbian,
        alpha: float = DEFAULT_ALPHA,
        neutral_prior: float = NEUTRAL_PRIOR,
        fallback_capability: Optional[str] = None,
        trust_interface: Any = None,
        beta: float = DEFAULT_BETA,
        trust_floor: float = DEFAULT_TRUST_FLOOR,
    ) -> None:
        """Initialize the router.

        Args:
            registry: An ``AgentRegistry`` (read for capabilities, scores,
                governance state).
            hebbian: A ``HebbianWeightManager`` (read for average agent weight).
            alpha: Blend factor in ``[0, 1]``; weight on the Hebbian signal.
            neutral_prior: Hebbian signal used when no history exists (cold
                start), so new agents are neither rewarded nor penalised.
            fallback_capability: Capability to route to when the requested one
                has no eligible agent (or the task omits a capability). ``None``
                keeps strict matching (raise on no match).
            trust_interface: A ``TrustInterface`` (read for agent trust score).
                ``None`` disables the trust signal entirely — the router falls
                back to the two-signal blend (composite + Hebbian).
            beta: Blend factor in ``[0, 1]``; weight on the trust signal. The
                composite term carries ``1 - alpha - beta``; alpha + beta is
                clamped to ``<= 1`` to keep the blend a convex combination.
            trust_floor: Hard cutoff in ``[0, 1]``. Agents whose trust score
                falls below this threshold are excluded from candidacy before
                blending. ``0`` (the default) disables floor exclusion.
        """
        self.registry = registry
        self.hebbian = hebbian
        self.alpha = max(0.0, min(1.0, float(alpha)))
        # Clamp beta so alpha + beta stays in [0, 1]; without this a misconfig
        # (env var typo, hand-wired test) could produce a negative composite
        # weight and silently invert ranking.
        self.beta = max(0.0, min(1.0 - self.alpha, float(beta)))
        self.neutral_prior = neutral_prior
        self.fallback_capability = fallback_capability or None
        self.trust_interface = trust_interface
        self.trust_floor = max(0.0, min(1.0, float(trust_floor)))

    def route(self, task: Dict[str, Any]) -> RoutingDecision:
        """Route a task to the highest blended-score eligible agent.

        Resolution order: the task's ``required_capability`` first, then the
        configured ``fallback_capability`` (if any).

        Args:
            task: Task dict; should contain ``required_capability``.

        Returns:
            RoutingDecision: The chosen agent plus the per-candidate breakdown.

        Raises:
            ValueError: If no capability is available to route on, or no
                eligible agent matches the requested or fallback capability.
        """
        capability = task.get("required_capability")
        routing_scope = str(task.get("routing_scope") or capability or "").strip()
        atp_action_type = task.get("atp_action_type")
        if not capability:
            # No capability at all: only routable if a fallback is configured.
            if self.fallback_capability:
                decision = self._route_for(
                    self.fallback_capability,
                    fell_back_from="<unspecified>",
                    routing_scope=routing_scope or self.fallback_capability,
                    atp_action_type=atp_action_type,
                )
                if decision is not None:
                    return decision
            raise ValueError(
                "Task dictionary must contain a 'required_capability' key."
            )

        decision = self._route_for(
            capability,
            routing_scope=routing_scope or capability,
            atp_action_type=atp_action_type,
        )
        if decision is not None:
            return decision

        # Fallback: nothing advertised the requested capability.
        if self.fallback_capability and self.fallback_capability != capability:
            decision = self._route_for(
                self.fallback_capability,
                fell_back_from=capability,
                routing_scope=routing_scope or capability,
                atp_action_type=atp_action_type,
            )
            if decision is not None:
                return decision

        raise ValueError(f"No agent found with the required capability: {capability}")

    def route_name(self, task: Dict[str, Any]) -> str:
        """Convenience: route and return only the selected agent name."""
        return self.route(task).agent_name

    # ------------------------------------------------------------------
    # Internals (all defensive: never raise on a bad/mocked data source)
    # ------------------------------------------------------------------

    def _route_for(
        self,
        capability: str,
        fell_back_from: Optional[str] = None,
        *,
        routing_scope: Optional[str] = None,
        atp_action_type: Optional[str] = None,
    ) -> Optional[RoutingDecision]:
        """Score and choose among agents with ``capability``; None if there are none."""
        # First pass: capability + governance (quarantine/suspension) filter.
        eligible = [
            agent.name
            for agent in self.registry.get_all_agents()
            if capability in getattr(agent, "capabilities", [])
            and not self._is_blocked(agent.name)
        ]
        if not eligible:
            return None

        # Read trust per candidate up front so we can apply the floor and reuse
        # the value in the blend without a second lookup. _trust_score returns
        # the neutral prior on any error, so missing trust never blocks routing.
        trusts = {name: self._trust_score(name) for name in eligible}

        # Second pass: trust floor. Skipped entirely when trust_floor == 0
        # (the default) so legacy callers see no behavior change.
        if self.trust_floor > 0.0:
            candidates = [n for n in eligible if trusts[n] >= self.trust_floor]
        else:
            candidates = eligible
        if not candidates:
            if self.trust_floor > 0.0 and eligible:
                # Eligible agents exist but every one was below the trust
                # floor. Do not fall through to the "no capable agent"
                # path -- if the caller wanted llm_chat as a backup, it
                # would also have to clear the same floor. Raise instead
                # so the user sees the real reason routing failed.
                raise ValueError(
                    f"All candidates for capability {capability!r} are "
                    f"below trust floor {self.trust_floor:.2f}"
                )
            return None

        raw = {}
        learning_scope = routing_scope or capability
        for name in candidates:
            base = self._hebbian_weight(name, learning_scope)
            pair_bonus = self._pair_bonus(name)
            timing_score = self._timing_score(name, learning_scope)
            stability = self._stability_signal(name, learning_scope)
            effective = None
            if base is not None or timing_score is not None or pair_bonus != 0.0:
                effective = max(
                    0.0,
                    float(base or 0.0) + float(timing_score or 0.0) + pair_bonus,
                )
            raw[name] = (
                self._composite(name),
                base,
                pair_bonus,
                timing_score,
                effective,
                stability,
            )
        max_heb = max(
            (values[4] for values in raw.values() if values[4] is not None),
            default=0.0,
        )
        composite_weight = max(0.0, 1.0 - self.alpha - self.beta)

        scored: List[CandidateScore] = []
        for name in candidates:
            (
                composite,
                scoped_heb,
                pair_bonus,
                timing_score,
                effective,
                stability,
            ) = raw[name]
            # Cold start (no weights anywhere) -> neutral prior for everyone, so
            # ranking collapses to the composite + trust portion.
            if effective is None:
                heb_raw = 0.0
                heb_norm = self.neutral_prior
            else:
                heb_raw = float(scoped_heb or 0.0)
                heb_norm = effective / max_heb if max_heb > 0 else self.neutral_prior
            trust = trusts[name]
            blended = (
                composite_weight * composite + self.alpha * heb_norm + self.beta * trust
            )
            scored.append(
                CandidateScore(
                    name=name,
                    composite=composite,
                    hebbian_weight=heb_raw,
                    hebbian_norm=heb_norm,
                    trust_score=trust,
                    blended=blended,
                    pair_bonus=pair_bonus,
                    timing_score=timing_score,
                    hebbian_effective=float(effective or 0.0),
                    oscillation_rate=stability["oscillation_rate"],
                    sentinel_alert=stability["alert_active"],
                    sentinel_samples=stability["sample_count"],
                )
            )

        # Deterministic order: highest blended, then composite; name ascending
        # within ties (stable sort: sort by name first, then by the metrics).
        scored.sort(key=lambda c: c.name)
        scored.sort(key=lambda c: (c.blended, c.composite), reverse=True)
        best = scored[0]

        if fell_back_from is not None:
            logger.info(
                "Hebbian routing FALLBACK (%r -> capability %r, "
                "alpha=%.2f beta=%.2f) -> %s",
                fell_back_from,
                capability,
                self.alpha,
                self.beta,
                best.name,
            )
        else:
            logger.info(
                "Hebbian routing (alpha=%.2f beta=%.2f) -> %s "
                "(blended=%.3f, composite=%.3f, heb=%.3f, trust=%.2f) "
                "over %d candidate(s)",
                self.alpha,
                self.beta,
                best.name,
                best.blended,
                best.composite,
                best.hebbian_weight,
                best.trust_score,
                len(scored),
            )
        return RoutingDecision(
            agent_name=best.name,
            alpha=self.alpha,
            beta=self.beta,
            trust_floor=self.trust_floor,
            candidates=scored,
            fallback_from=fell_back_from if fell_back_from != "<unspecified>" else None,
            capability=capability,
            routing_scope=learning_scope,
            atp_action_type=(str(atp_action_type) if atp_action_type else None),
        )

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

    def _hebbian_weight(self, name: str, task_type: str) -> Optional[float]:
        """Task-type weight, falling back to legacy agent-wide history."""
        try:
            get_scoped = getattr(self.hebbian, "get_task_type_weight", None)
            if callable(get_scoped):
                scoped_weight = get_scoped(name, task_type)
                if scoped_weight is not None:
                    return max(0.0, float(scoped_weight))
                has_scoped = getattr(self.hebbian, "has_task_type_history", None)
                if callable(has_scoped) and has_scoped(name):
                    # This agent has migrated to scoped learning, but this task
                    # type is new. Keep it at the neutral prior rather than
                    # leaking performance from an unrelated capability.
                    return None
            return max(0.0, float(self.hebbian.get_agent_average_weight(name)))
        except Exception:  # mocked/missing source -> treat as no history
            return 0.0

    def _trust_score(self, name: str) -> float:
        """Trust value in [0, 1] for an agent; neutral prior if unavailable.

        When ``trust_interface`` is ``None`` (trust signal disabled at
        construction time), every candidate reads the neutral prior so the
        beta term contributes a constant and ranking collapses to composite
        + Hebbian — the same behavior as ``beta == 0``.
        """
        # The registry is the execution/governance source of truth and is
        # updated atomically with Hebbian fields. Prefer it so a newly recorded
        # violation affects the very next route even before any cross-store
        # trust synchronization occurs.
        try:
            state = self.registry.get_governance_state(name)
            registry_score = state.get("trust_score") if state else None
            if registry_score is not None:
                return max(0.0, min(1.0, float(registry_score)))
        except Exception:  # pragma: no cover - defensive
            pass
        if self.trust_interface is None:
            return NEUTRAL_TRUST
        try:
            score = self.trust_interface.get_trust_score(name)
            # TrustInterface returns a TrustScore dataclass; some test doubles
            # may return a plain float. Accept both.
            raw = getattr(score, "score", score)
            return max(0.0, min(1.0, float(raw)))
        except Exception:  # mocked/missing source -> neutral prior
            return NEUTRAL_TRUST

    def _pair_bonus(self, name: str) -> float:
        """Sequential hand-off bonus from the last selected agent."""
        try:
            getter = getattr(self.hebbian, "get_pair_bonus", None)
            if not callable(getter):
                return 0.0
            return max(-0.5, min(0.5, float(getter(name))))
        except Exception:  # pragma: no cover - defensive
            return 0.0

    def _timing_score(self, name: str, task_type: str) -> Optional[float]:
        """Rolling timing/performance activation, or None on cold start."""
        try:
            getter = getattr(self.hebbian, "get_timing_score", None)
            if not callable(getter):
                return None
            score = getter(name, task_type)
            if score is None:
                return None
            return max(0.0, min(1.0, float(score)))
        except Exception:  # pragma: no cover - defensive
            return None

    def _stability_signal(self, name: str, task_type: str) -> dict:
        """Return observational sentinel state without altering route ranking."""
        neutral = {
            "oscillation_rate": 0.0,
            "alert_active": False,
            "sample_count": 0,
        }
        try:
            getter = getattr(self.hebbian, "get_stability_signal", None)
            if not callable(getter):
                return neutral
            signal = getter(name, task_type) or {}
            return {
                "oscillation_rate": max(
                    0.0, min(1.0, float(signal.get("oscillation_rate", 0.0)))
                ),
                "alert_active": bool(signal.get("alert_active", False)),
                "sample_count": max(0, int(signal.get("sample_count", 0))),
            }
        except Exception:  # pragma: no cover - defensive
            return neutral
