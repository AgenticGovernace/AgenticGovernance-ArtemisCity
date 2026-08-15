"""
Self-Update Governance — CI/CD-style approval workflow for agent self-modification.

When an agent proposes a change to its own configuration, routing weights, or
workflow definitions, the proposal flows through this governor:

    1. Agent trust score determines the approval tier.
    2. Sandbox testing validates the change against synthetic queries.
    3. Static analysis lints the proposal for policy violations.
    4. Performance regression checks compare against baseline.
    5. Decision: auto-approve, monitor, or require human sign-off.

Part of the Artemis City Governance Layer.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.helpers import logger


class ApprovalLevel(Enum):
    """Determines how much oversight a proposal requires."""

    AUTO_APPROVE = "auto"           # Composite score > 85%
    MONITORED_APPROVE = "monitored" # Composite score 70-85%
    HUMAN_REQUIRED = "human"        # Composite score < 70%


class ProposalStatus(Enum):
    """Lifecycle states for a self-update proposal."""

    PENDING = "pending"
    SANDBOX_TESTING = "sandbox_testing"
    LINT_CHECK = "lint_check"
    PERF_CHECK = "perf_check"
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING_HUMAN_REVIEW = "pending_human_review"
    ROLLED_BACK = "rolled_back"


@dataclass
class WorkflowChange:
    """Describes a proposed modification to agent configuration or workflow."""

    change_type: str              # e.g., "routing_weight", "config_update", "workflow_add"
    target_component: str         # e.g., "agent_router", "memory_bus", "hebbian_layer"
    description: str
    proposed_diff: Dict[str, Any] = field(default_factory=dict)
    rollback_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxTestResults:
    """Results from running synthetic queries against a proposed change."""

    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0

    @property
    def failure_rate(self) -> float:
        if self.total_tests == 0:
            return 0.0
        return (self.failed + self.errors) / self.total_tests

    @property
    def pass_rate(self) -> float:
        if self.total_tests == 0:
            return 0.0
        return self.passed / self.total_tests


@dataclass
class ApprovalDecision:
    """Outcome of the governance evaluation pipeline."""

    status: str
    reason: str
    requires_human: bool = False
    staged_rollout: bool = False
    sandbox_results: Optional[SandboxTestResults] = None
    performance_delta: float = 0.0
    approval_level: Optional[ApprovalLevel] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        result = {
            "status": self.status,
            "reason": self.reason,
            "requires_human": self.requires_human,
            "staged_rollout": self.staged_rollout,
            "performance_delta": self.performance_delta,
            "timestamp": self.timestamp,
        }
        if self.approval_level:
            result["approval_level"] = self.approval_level.value
        if self.sandbox_results:
            result["sandbox_pass_rate"] = self.sandbox_results.pass_rate
            result["sandbox_failure_rate"] = self.sandbox_results.failure_rate
        return result


class SelfUpdateGovernor:
    """
    Evaluates and gates agent self-modification proposals.

    Flow:
        propose → evaluate_proposal → (sandbox test) → (lint) → (perf check) → decision

    Configuration:
        sandbox_test_count: Number of synthetic queries per proposal (default: 1000)
        max_failure_rate: Maximum sandbox failure rate (default: 5%)
        max_perf_regression: Maximum latency regression (default: 20%)
    """

    def __init__(
        self,
        registry=None,
        sandbox_test_count: int = 1000,
        max_failure_rate: float = 0.05,
        max_perf_regression: float = 0.20,
        log_dir: str = "logs/governance",
    ):
        self.registry = registry
        self.sandbox_test_count = sandbox_test_count
        self.max_failure_rate = max_failure_rate
        self.max_perf_regression = max_perf_regression
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._proposal_history: List[Dict] = []

    async def evaluate_proposal(
        self,
        proposing_agent_id: str,
        proposed_change: WorkflowChange,
    ) -> ApprovalDecision:
        """
        Run the full evaluation pipeline for a self-update proposal.

        Steps:
            1. Check agent trust score → determine approval tier
            2. Run sandbox tests with synthetic queries
            3. Run static analysis / lint checks
            4. Check for performance regression
            5. Issue decision

        Args:
            proposing_agent_id: ID of the agent proposing the change.
            proposed_change: The proposed modification.

        Returns:
            ApprovalDecision with status, reason, and metadata.
        """
        start_time = time.perf_counter()

        # Step 1: Determine approval level from agent trust score
        approval_level = self._determine_approval_level(proposing_agent_id)

        # Step 2: Run sandbox tests
        sandbox_results = await self._run_sandbox_tests(proposed_change)

        # Step 3: Static analysis
        lint_issues = self._lint_proposal(proposed_change)

        # Step 4: Performance regression check
        perf_regression = await self._check_performance(proposed_change)

        eval_latency_ms = (time.perf_counter() - start_time) * 1000

        # Decision logic
        decision = self._make_decision(
            approval_level=approval_level,
            sandbox_results=sandbox_results,
            lint_issues=lint_issues,
            perf_regression=perf_regression,
        )

        # Log the proposal evaluation
        self._log_proposal(
            proposing_agent_id=proposing_agent_id,
            proposed_change=proposed_change,
            decision=decision,
            eval_latency_ms=eval_latency_ms,
        )

        return decision

    def evaluate_proposal_sync(
        self,
        proposing_agent_id: str,
        proposed_change: WorkflowChange,
    ) -> ApprovalDecision:
        """Synchronous wrapper for evaluate_proposal (for non-async contexts)."""
        approval_level = self._determine_approval_level(proposing_agent_id)

        # Simplified sync evaluation
        if approval_level == ApprovalLevel.HUMAN_REQUIRED:
            return ApprovalDecision(
                status="pending_human_review",
                reason="Low agent trust score",
                requires_human=True,
                approval_level=approval_level,
            )

        lint_issues = self._lint_proposal(proposed_change)
        if lint_issues:
            return ApprovalDecision(
                status="rejected",
                reason=f"Lint issues: {', '.join(lint_issues)}",
                requires_human=False,
                approval_level=approval_level,
            )

        staged = approval_level == ApprovalLevel.MONITORED_APPROVE
        return ApprovalDecision(
            status="approved",
            reason="Passed sync evaluation",
            requires_human=False,
            staged_rollout=staged,
            approval_level=approval_level,
        )

    def _determine_approval_level(self, agent_id: str) -> ApprovalLevel:
        """Map agent trust score to approval tier."""
        if self.registry is None:
            return ApprovalLevel.HUMAN_REQUIRED

        scores = getattr(self.registry, "scores", {})
        agent_score = scores.get(agent_id)
        if agent_score is None:
            return ApprovalLevel.HUMAN_REQUIRED

        composite = agent_score.composite_score
        if composite > 0.85:
            return ApprovalLevel.AUTO_APPROVE
        elif composite > 0.70:
            return ApprovalLevel.MONITORED_APPROVE
        else:
            return ApprovalLevel.HUMAN_REQUIRED

    async def _run_sandbox_tests(
        self, change: WorkflowChange
    ) -> SandboxTestResults:
        """
        Run synthetic queries against the proposed change in isolation.

        In production this would spin up an isolated environment and replay
        test queries. Current implementation returns baseline results.
        """
        # Placeholder: returns clean results for now.
        # Real implementation would execute change in sandbox container.
        return SandboxTestResults(
            total_tests=self.sandbox_test_count,
            passed=self.sandbox_test_count,
            failed=0,
            errors=0,
            avg_latency_ms=45.0,
            p95_latency_ms=120.0,
        )

    def _lint_proposal(self, change: WorkflowChange) -> List[str]:
        """
        Static analysis of the proposed change.

        Checks:
        - No escalation of agent privileges
        - No removal of safety constraints
        - Change description is non-empty
        - Target component exists
        """
        issues = []

        if not change.description:
            issues.append("Missing change description")

        if not change.target_component:
            issues.append("Missing target component")

        # Check for privilege escalation patterns
        diff_str = json.dumps(change.proposed_diff).lower()
        dangerous_patterns = [
            "admin", "root", "sudo", "bypass_sandbox",
            "disable_governance", "remove_whitelist",
        ]
        for pattern in dangerous_patterns:
            if pattern in diff_str:
                issues.append(f"Suspicious pattern detected: '{pattern}'")

        return issues

    async def _check_performance(self, change: WorkflowChange) -> float:
        """
        Compare proposed change against performance baseline.

        Returns:
            Float representing regression percentage (0.0 = no regression,
            0.20 = 20% slower).
        """
        # Placeholder: real implementation would benchmark against baseline
        return 0.0

    def _make_decision(
        self,
        approval_level: ApprovalLevel,
        sandbox_results: SandboxTestResults,
        lint_issues: List[str],
        perf_regression: float,
    ) -> ApprovalDecision:
        """Apply decision logic across all evaluation signals."""

        # Human required — always escalate
        if approval_level == ApprovalLevel.HUMAN_REQUIRED:
            return ApprovalDecision(
                status="pending_human_review",
                reason="Agent trust score below threshold",
                requires_human=True,
                sandbox_results=sandbox_results,
                performance_delta=perf_regression,
                approval_level=approval_level,
            )

        # Lint failures — reject
        if lint_issues:
            return ApprovalDecision(
                status="rejected",
                reason=f"Static analysis failed: {'; '.join(lint_issues)}",
                requires_human=False,
                sandbox_results=sandbox_results,
                approval_level=approval_level,
            )

        # Sandbox failures — reject
        if sandbox_results.failure_rate > self.max_failure_rate:
            return ApprovalDecision(
                status="rejected",
                reason=(
                    f"Sandbox failure rate {sandbox_results.failure_rate:.1%} "
                    f"exceeds {self.max_failure_rate:.1%} threshold"
                ),
                requires_human=False,
                sandbox_results=sandbox_results,
                approval_level=approval_level,
            )

        # Performance regression — require human review
        if perf_regression > self.max_perf_regression:
            return ApprovalDecision(
                status="rejected",
                reason=(
                    f"Performance regression {perf_regression:.1%} "
                    f"exceeds {self.max_perf_regression:.1%} threshold"
                ),
                requires_human=True,
                sandbox_results=sandbox_results,
                performance_delta=perf_regression,
                approval_level=approval_level,
            )

        # All checks passed
        staged = approval_level == ApprovalLevel.MONITORED_APPROVE
        return ApprovalDecision(
            status="approved",
            reason="Passed all governance checks",
            requires_human=False,
            staged_rollout=staged,
            sandbox_results=sandbox_results,
            performance_delta=perf_regression,
            approval_level=approval_level,
        )

    def _log_proposal(
        self,
        proposing_agent_id: str,
        proposed_change: WorkflowChange,
        decision: ApprovalDecision,
        eval_latency_ms: float,
    ):
        """Persist proposal evaluation to governance log."""
        record = {
            "event": "self_update_proposal",
            "proposing_agent": proposing_agent_id,
            "change_type": proposed_change.change_type,
            "target_component": proposed_change.target_component,
            "description": proposed_change.description,
            "decision": decision.to_dict(),
            "eval_latency_ms": eval_latency_ms,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._proposal_history.append(record)

        log_file = self._log_dir / "proposals.jsonl"
        try:
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            logger.warning("Failed to persist governance proposal log")

        logger.info(
            f"[GOVERNANCE] Proposal by '{proposing_agent_id}' "
            f"({proposed_change.change_type}): {decision.status}"
        )

    def get_proposal_history(self, limit: int = 50) -> List[Dict]:
        """Return recent proposal evaluations."""
        return self._proposal_history[-limit:]
