"""Self-update approval tiers.

Classifies a proposed self-update into one of three approval tiers per
``GOVERNANCE.md``:

* **auto**      — trust > 0.9, < 1% code change, backwards-compatible, no new
  deps. Deployed without human intervention.
* **monitored** — trust 0.7-0.9, 1-10% change, additive API, new deps require
  review. Deployed on human approval.
* **human**     — trust < 0.7 (or unknown agent), > 10% change, breaking
  changes, or any policy/governance change. Requires senior review.

The tier is the *maximum* of the trust-implied tier and any risk escalators:
a high-trust agent proposing a breaking or policy change is still routed to
human review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

# Trust thresholds from GOVERNANCE.md tier criteria.
TRUST_AUTO_MIN = 0.9
TRUST_MONITORED_MIN = 0.7

# Risk thresholds.
CODE_CHANGE_HUMAN_MIN = 0.10  # > 10% of codebase -> human
CODE_CHANGE_MONITORED_MIN = 0.01  # > 1% -> at least monitored


class ApprovalTier(str, Enum):
    """Enumerate the approval tiers used for self-update governance.
    """
    AUTO = "auto"
    MONITORED = "monitored"
    HUMAN = "human"


@dataclass
class UpdateProposal:
    """A proposed self-update and its risk characteristics."""

    agent_name: str
    code_change_ratio: float = 0.0  # fraction of codebase changed [0, 1]
    breaking_changes: bool = False
    new_dependencies: bool = False
    policy_change: bool = False  # touches sandbox/approval policy
    affects_governance: bool = False  # modifies the governance system itself


@dataclass
class ApprovalDecision:
    """Represent the approval outcome returned by the self-update governor.
    
    Attributes:
        tier (ApprovalTier): Stored value on the ApprovalDecision instance.
        auto_approved (bool): Stored value on the ApprovalDecision instance.
        requires_human (bool): Stored value on the ApprovalDecision instance.
        reasons (List[str]): Stored value on the ApprovalDecision instance.
    """
    tier: ApprovalTier
    auto_approved: bool
    requires_human: bool
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """To dict.
        
        Returns:
            dict: Dictionary containing the resulting data.
        """
        return {
            "tier": self.tier.value,
            "auto_approved": self.auto_approved,
            "requires_human": self.requires_human,
            "reasons": self.reasons,
        }


def _decision(tier: ApprovalTier, reasons: List[str]) -> ApprovalDecision:
    return ApprovalDecision(
        tier=tier,
        auto_approved=(tier == ApprovalTier.AUTO),
        requires_human=(tier == ApprovalTier.HUMAN),
        reasons=reasons,
    )


class SelfUpdateGovernor:
    """Maps (proposal, trust score) -> approval tier."""

    def classify(
        self,
        proposal: UpdateProposal,
        trust_score: float,
        has_history: bool = True,
    ) -> ApprovalDecision:
        """Classify a proposal. ``has_history=False`` forces human review
        ("unknown agent") regardless of the computed trust score.
        
        Args:
            proposal (UpdateProposal): Self-update proposal being classified.
            trust_score (float): Trust score used for approval or routing decisions.
            has_history (bool): Has history value used by this operation.
        
        Returns:
            ApprovalDecision: Resulting ApprovalDecision value produced by the operation.
        """
        reasons: List[str] = []

        # --- Hard escalators: always human review ---
        if proposal.affects_governance:
            reasons.append("modifies the governance system itself")
        if proposal.policy_change:
            reasons.append("changes sandbox/approval policy")
        if proposal.breaking_changes:
            reasons.append("breaking API change")
        if proposal.code_change_ratio > CODE_CHANGE_HUMAN_MIN:
            reasons.append(
                f"code change {proposal.code_change_ratio:.0%} exceeds 10%"
            )
        if not has_history:
            reasons.append("unknown agent (no execution history)")
        if trust_score < TRUST_MONITORED_MIN:
            reasons.append(f"trust score {trust_score:.2f} below 0.70")
        if reasons:
            return _decision(ApprovalTier.HUMAN, reasons)

        # --- Monitored escalators ---
        if proposal.new_dependencies:
            reasons.append("new dependencies require review")
        if proposal.code_change_ratio > CODE_CHANGE_MONITORED_MIN:
            reasons.append(
                f"code change {proposal.code_change_ratio:.0%} exceeds 1%"
            )
        if trust_score < TRUST_AUTO_MIN:
            reasons.append(f"trust score {trust_score:.2f} below 0.90")
        if reasons:
            return _decision(ApprovalTier.MONITORED, reasons)

        # --- Auto-approve ---
        return _decision(
            ApprovalTier.AUTO,
            [f"low-risk change, trust score {trust_score:.2f} >= 0.90"],
        )
