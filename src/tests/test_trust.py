"""Tests for the trust-score engine (src/governance/trust.py)."""

import pytest
from src.governance.trust import (
    TrustMetrics,
    WEIGHT_AUDIT_APPROVALS,
    WEIGHT_CODE_QUALITY,
    WEIGHT_SECURITY,
    WEIGHT_SUCCESS_RATE,
    WEIGHT_UPTIME,
    compute_trust_score,
    security_score,
    success_rate,
    trust_breakdown,
    uptime,
)


class TestWeights:
    def test_weights_sum_to_one(self):
        total = (
            WEIGHT_SUCCESS_RATE
            + WEIGHT_SECURITY
            + WEIGHT_CODE_QUALITY
            + WEIGHT_AUDIT_APPROVALS
            + WEIGHT_UPTIME
        )
        assert abs(total - 1.0) < 1e-9


class TestSubMetrics:
    def test_success_rate_no_history_is_one(self):
        assert success_rate(TrustMetrics(total_executions=0)) == 1.0

    def test_success_rate_ratio(self):
        m = TrustMetrics(successful_executions=8, total_executions=10)
        assert success_rate(m) == 0.8

    def test_security_score_clean(self):
        assert security_score(TrustMetrics(recent_violation_count=0)) == 1.0

    def test_security_score_decreases_with_violations(self):
        assert security_score(TrustMetrics(recent_violation_count=3)) == pytest.approx(0.7)

    def test_security_score_floors_at_zero(self):
        assert security_score(TrustMetrics(recent_violation_count=50)) == 0.0

    def test_uptime_no_hours_is_one(self):
        assert uptime(TrustMetrics(total_hours=0)) == 1.0

    def test_uptime_ratio(self):
        m = TrustMetrics(downtime_hours=3, total_hours=30)
        assert uptime(m) == pytest.approx(0.9)


class TestComputeScore:
    def test_pristine_agent_scores_one(self):
        # No failures, no violations, perfect quality -> 1.0
        assert compute_trust_score(TrustMetrics()) == pytest.approx(1.0)

    def test_score_in_unit_interval(self):
        m = TrustMetrics(
            successful_executions=5,
            total_executions=10,
            recent_violation_count=2,
            coverage_ratio=0.5,
            passed_lints=False,
            no_dead_code=True,
            approved_updates=1,
            total_update_attempts=4,
            downtime_hours=12,
            total_hours=100,
        )
        score = compute_trust_score(m)
        assert 0.0 <= score <= 1.0

    def test_violations_lower_score(self):
        clean = compute_trust_score(TrustMetrics(recent_violation_count=0))
        dirty = compute_trust_score(TrustMetrics(recent_violation_count=5))
        assert dirty < clean

    def test_manual_weighted_sum(self):
        m = TrustMetrics(
            successful_executions=9,
            total_executions=10,  # success_rate 0.9
            recent_violation_count=1,  # security 0.9
            coverage_ratio=1.0,
            passed_lints=True,
            no_dead_code=True,  # code_quality 1.0
            approved_updates=8,
            total_update_attempts=10,  # audit 0.8
            downtime_hours=0,
            total_hours=10,  # uptime 1.0
        )
        expected = (
            0.9 * WEIGHT_SUCCESS_RATE
            + 0.9 * WEIGHT_SECURITY
            + 1.0 * WEIGHT_CODE_QUALITY
            + 0.8 * WEIGHT_AUDIT_APPROVALS
            + 1.0 * WEIGHT_UPTIME
        )
        assert compute_trust_score(m) == pytest.approx(expected)


class TestBreakdown:
    def test_breakdown_structure(self):
        bd = trust_breakdown(TrustMetrics())
        assert set(bd) == {"components", "weights", "contributions"}
        assert set(bd["components"]) == {
            "success_rate",
            "security_score",
            "code_quality",
            "audit_approvals",
            "uptime",
        }

    def test_contributions_sum_to_score(self):
        m = TrustMetrics(successful_executions=7, total_executions=10, recent_violation_count=2)
        bd = trust_breakdown(m)
        assert sum(bd["contributions"].values()) == pytest.approx(compute_trust_score(m))


class TestHistoryFlag:
    def test_has_execution_history(self):
        assert TrustMetrics(total_executions=1).has_execution_history is True
        assert TrustMetrics(total_executions=0).has_execution_history is False
