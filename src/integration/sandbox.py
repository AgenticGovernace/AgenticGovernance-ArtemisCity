"""Per-agent sandbox enforcement with tool whitelisting and violation logging.

Implements the runtime permission checks described in GOVERNANCE.md:
each agent has a whitelist of callable tools with optional path / operation
constraints. Denied actions are recorded as violations through the
``AgentRegistry``, which auto-quarantines an agent on its third strike.

The registry remains the single source of truth for violation counts and
quarantine state; the sandbox only enforces and reports.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import List, Optional

from src.utils.helpers import logger

# Violation types mirror VIOLATION_TYPES in agent_registry / GOVERNANCE.md.
VIOLATION_UNAUTHORIZED_TOOL = "unauthorized_tool"
VIOLATION_UNAUTHORIZED_PATH = "unauthorized_path"
VIOLATION_RATE_LIMIT = "rate_limit"
VIOLATION_MISSING_CAPABILITY = "missing_capability"
VIOLATION_UNSAFE_NETWORK = "unsafe_network"


@dataclass
class ToolPolicy:
    """A single whitelisted tool and the constraints on its use."""

    name: str
    paths: List[str] = field(default_factory=list)  # glob patterns; empty = any
    operations: List[str] = field(default_factory=list)  # empty = any

    def allows_path(self, path: str) -> bool:
        if not self.paths:
            return True
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.paths)

    def allows_operation(self, operation: Optional[str]) -> bool:
        if not self.operations:
            return True
        return operation in self.operations


@dataclass
class CheckResult:
    """Outcome of a sandbox permission check."""

    allowed: bool
    violation_type: Optional[str] = None
    reason: Optional[str] = None


class AgentSandbox:
    """Enforces a tool whitelist for one agent, reporting denials to the registry.

    Parameters
    ----------
    agent_name:
        Name of the agent this sandbox guards (must exist in the registry).
    policies:
        Iterable of :class:`ToolPolicy` defining the agent's whitelist.
    registry:
        An ``AgentRegistry`` used to record violations and consult quarantine
        state. Optional so the sandbox can be unit-tested in isolation, but a
        registry is required for violations to be persisted / counted.
    """

    def __init__(self, agent_name, policies=None, registry=None):
        self.agent_name = agent_name
        self.registry = registry
        self.policies = {p.name: p for p in (policies or [])}

    def check_action(
        self,
        tool_name: str,
        path: Optional[str] = None,
        operation: Optional[str] = None,
    ) -> CheckResult:
        """Check whether the agent may invoke ``tool_name``.

        Returns a :class:`CheckResult`. On denial, a violation is recorded
        through the registry (which may quarantine the agent), and any
        subsequent check while quarantined is denied outright.
        """
        # A quarantined agent is denied everything until manually cleared.
        if self.registry is not None and self.registry.is_quarantined(
            self.agent_name
        ):
            return CheckResult(
                allowed=False,
                violation_type=None,
                reason="agent is quarantined",
            )

        policy = self.policies.get(tool_name)
        if policy is None:
            return self._deny(
                VIOLATION_UNAUTHORIZED_TOOL,
                f"tool {tool_name!r} not in whitelist",
                {"tool_name": tool_name, "path": path, "operation": operation},
            )

        if path is not None and not policy.allows_path(path):
            return self._deny(
                VIOLATION_UNAUTHORIZED_PATH,
                f"path {path!r} outside whitelist for {tool_name!r}",
                {
                    "tool_name": tool_name,
                    "requested_path": path,
                    "allowed_paths": policy.paths,
                },
            )

        if not policy.allows_operation(operation):
            return self._deny(
                VIOLATION_UNAUTHORIZED_PATH,
                f"operation {operation!r} not permitted for {tool_name!r}",
                {
                    "tool_name": tool_name,
                    "operation": operation,
                    "allowed_operations": policy.operations,
                },
            )

        return CheckResult(allowed=True)

    def _deny(self, violation_type: str, reason: str, details: dict) -> CheckResult:
        """Record a violation and return a denial result."""
        logger.warning(
            "[SANDBOX_VIOLATION] agent=%s type=%s reason=%s",
            self.agent_name,
            violation_type,
            reason,
        )
        if self.registry is not None:
            self.registry.record_violation(
                self.agent_name, violation_type, details
            )
        return CheckResult(
            allowed=False, violation_type=violation_type, reason=reason
        )
