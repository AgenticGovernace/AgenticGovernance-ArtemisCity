"""Trust-score engine.

Implements the weighted trust-score formula from ``GOVERNANCE.md``. Each
contributing sub-metric is normalised to ``[0, 1]`` and combined with fixed
weights that sum to 1.0, so the resulting trust score is also in ``[0, 1]``.

A note on the security term
---------------------------
``GOVERNANCE.md`` prints the security coefficient as ``-0.25`` while also
defining ``SecurityViolations = max(0, 1 - 0.1 * count)`` — i.e. a *goodness*
measure (1.0 = clean, 0.0 = many violations). Applying a negative weight to a
goodness measure would make violations *raise* trust, and the five weights
would no longer sum to 1.0. We therefore use ``+0.25`` (the only value for
which 0.35 + 0.25 + 0.20 + 0.15 + 0.05 == 1.0), so violations correctly lower
trust. The doc's printed sign is treated as a typo.
"""

from __future__ import annotations

from dataclasses import dataclass

# Weights (sum to 1.0). See module docstring re: the security sign.
WEIGHT_SUCCESS_RATE = 0.35
WEIGHT_SECURITY = 0.25
WEIGHT_CODE_QUALITY = 0.20
WEIGHT_AUDIT_APPROVALS = 0.15
WEIGHT_UPTIME = 0.05

# SecurityScore = max(0, 1 - VIOLATION_PENALTY_PER * recent_violation_count)
VIOLATION_PENALTY_PER = 0.1


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass
class TrustMetrics:
    """Inputs to the trust-score calculation.

    Ratio-based "goodness" metrics default to a clean slate (1.0 once
    normalised) when there's no history, so an agent's score is dragged down
    by *evidence* (failures, violations) rather than by absence of data. The
    "unknown agent" caution lives in the approval governor, not here.
    """

    successful_executions: int = 0
    total_executions: int = 0
    recent_violation_count: int = 0
    coverage_ratio: float = 1.0
    passed_lints: bool = True
    no_dead_code: bool = True
    approved_updates: int = 0
    total_update_attempts: int = 0
    downtime_hours: float = 0.0
    total_hours: float = 0.0

    @property
    def has_execution_history(self) -> bool:
        """Return whether execution history.

        Returns:
            bool: Boolean outcome for the requested check.
        """
        return self.total_executions > 0


def success_rate(m: TrustMetrics) -> float:
    """Success rate.

    Args:
        m (TrustMetrics): Trust metrics input used to compute a score.

    Returns:
        float: Numeric result produced by the operation.
    """
    if m.total_executions <= 0:
        return 1.0
    return _clamp(m.successful_executions / m.total_executions)


def security_score(m: TrustMetrics) -> float:
    """Security score.

    Args:
        m (TrustMetrics): Trust metrics input used to compute a score.

    Returns:
        float: Numeric result produced by the operation.
    """
    return max(0.0, 1.0 - VIOLATION_PENALTY_PER * max(0, m.recent_violation_count))


def code_quality(m: TrustMetrics) -> float:
    """Code quality.

    Args:
        m (TrustMetrics): Trust metrics input used to compute a score.

    Returns:
        float: Numeric result produced by the operation.
    """
    return _clamp(
        (
            _clamp(m.coverage_ratio)
            + (1.0 if m.passed_lints else 0.0)
            + (1.0 if m.no_dead_code else 0.0)
        )
        / 3.0
    )


def audit_approvals(m: TrustMetrics) -> float:
    """Audit approvals.

    Args:
        m (TrustMetrics): Trust metrics input used to compute a score.

    Returns:
        float: Numeric result produced by the operation.
    """
    if m.total_update_attempts <= 0:
        return 1.0
    return _clamp(m.approved_updates / m.total_update_attempts)


def uptime(m: TrustMetrics) -> float:
    """Uptime.

    Args:
        m (TrustMetrics): Trust metrics input used to compute a score.

    Returns:
        float: Numeric result produced by the operation.
    """
    if m.total_hours <= 0:
        return 1.0
    return _clamp(1.0 - m.downtime_hours / m.total_hours)


def trust_breakdown(m: TrustMetrics) -> dict[str, dict[str, float]]:
    """Return each normalized trust sub-metric and its weighted contribution.

    Args:
        m (TrustMetrics): Trust-metric inputs used for the calculation.

    Returns:
        Dict[str, Dict[str, float]]: Nested component, weight, and contribution values for the trust formula.
    """
    components = {
        "success_rate": success_rate(m),
        "security_score": security_score(m),
        "code_quality": code_quality(m),
        "audit_approvals": audit_approvals(m),
        "uptime": uptime(m),
    }
    weights = {
        "success_rate": WEIGHT_SUCCESS_RATE,
        "security_score": WEIGHT_SECURITY,
        "code_quality": WEIGHT_CODE_QUALITY,
        "audit_approvals": WEIGHT_AUDIT_APPROVALS,
        "uptime": WEIGHT_UPTIME,
    }
    contributions = {k: components[k] * weights[k] for k in components}
    return {
        "components": components,
        "weights": weights,
        "contributions": contributions,
    }


def compute_trust_score(m: TrustMetrics) -> float:
    """Compute the weighted trust score in ``[0, 1]``.

    Args:
        m (TrustMetrics): Trust metrics input used to compute a score.

    Returns:
        float: Numeric result produced by the operation.
    """
    return _clamp(
        success_rate(m) * WEIGHT_SUCCESS_RATE
        + security_score(m) * WEIGHT_SECURITY
        + code_quality(m) * WEIGHT_CODE_QUALITY
        + audit_approvals(m) * WEIGHT_AUDIT_APPROVALS
        + uptime(m) * WEIGHT_UPTIME
    )
