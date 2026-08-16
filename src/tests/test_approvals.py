"""Tests for the self-update approval tier classifier."""

import pytest

from src.governance.approvals import (ApprovalTier, SelfUpdateGovernor,
                                      UpdateProposal)


@pytest.fixture
def governor():
    """Governor.

    Returns:
        None: This function does not return a value.
    """
    return SelfUpdateGovernor()


def _proposal(**kwargs):
    return UpdateProposal(agent_name="Alpha", **kwargs)


class TestAutoTier:
    """Provide the TestAutoTier abstraction used by this module."""

    def test_low_risk_high_trust_auto(self, governor):
        """Test that low risk high trust auto.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(code_change_ratio=0.005), trust_score=0.95)
        assert d.tier == ApprovalTier.AUTO
        assert d.auto_approved is True
        assert d.requires_human is False

    def test_auto_requires_trust_above_090(self, governor):
        # 0.89 trust, tiny change -> monitored, not auto
        """Test that auto requires trust above 090.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(code_change_ratio=0.005), trust_score=0.89)
        assert d.tier == ApprovalTier.MONITORED


class TestMonitoredTier:
    """Provide the TestMonitoredTier abstraction used by this module."""

    def test_midrange_trust_monitored(self, governor):
        """Test that midrange trust monitored.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(code_change_ratio=0.0), trust_score=0.8)
        assert d.tier == ApprovalTier.MONITORED
        assert d.requires_human is False

    def test_new_deps_force_monitored(self, governor):
        """Test that new deps force monitored.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(new_dependencies=True), trust_score=0.99)
        assert d.tier == ApprovalTier.MONITORED

    def test_medium_code_change_monitored(self, governor):
        """Test that medium code change monitored.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(code_change_ratio=0.05), trust_score=0.95)
        assert d.tier == ApprovalTier.MONITORED


class TestHumanTier:
    """Provide the TestHumanTier abstraction used by this module."""

    def test_low_trust_human(self, governor):
        """Test that low trust human.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(), trust_score=0.5)
        assert d.tier == ApprovalTier.HUMAN
        assert d.requires_human is True

    def test_breaking_change_human_even_high_trust(self, governor):
        """Test that breaking change human even high trust.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(breaking_changes=True), trust_score=0.99)
        assert d.tier == ApprovalTier.HUMAN

    def test_large_change_human(self, governor):
        """Test that large change human.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(code_change_ratio=0.5), trust_score=0.99)
        assert d.tier == ApprovalTier.HUMAN

    def test_policy_change_human(self, governor):
        """Test that policy change human.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(policy_change=True), trust_score=0.99)
        assert d.tier == ApprovalTier.HUMAN

    def test_affects_governance_human(self, governor):
        """Test that affects governance human.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(affects_governance=True), trust_score=0.99)
        assert d.tier == ApprovalTier.HUMAN

    def test_unknown_agent_human(self, governor):
        """Test that unknown agent human.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(
            _proposal(code_change_ratio=0.0), trust_score=0.99, has_history=False
        )
        assert d.tier == ApprovalTier.HUMAN
        assert any("unknown agent" in r for r in d.reasons)


class TestDecisionShape:
    """Provide the TestDecisionShape abstraction used by this module."""

    def test_to_dict(self, governor):
        """Test that to dict.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        d = governor.classify(_proposal(code_change_ratio=0.005), trust_score=0.95)
        payload = d.to_dict()
        assert payload["tier"] == "auto"
        assert payload["auto_approved"] is True
        assert isinstance(payload["reasons"], list) and payload["reasons"]

    def test_reasons_present_for_each_tier(self, governor):
        """Test that reasons present for each tier.

        Args:
            governor: Governor value used by this operation.

        Returns:
            None: This function does not return a value.
        """
        for trust, expect in [
            (0.95, ApprovalTier.AUTO),
            (0.8, ApprovalTier.MONITORED),
            (0.5, ApprovalTier.HUMAN),
        ]:
            d = governor.classify(_proposal(), trust_score=trust)
            assert d.tier == expect
            assert d.reasons  # never empty
