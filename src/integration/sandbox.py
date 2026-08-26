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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from src.utils.helpers import logger, sanitize_for_log

# Violation types mirror VIOLATION_TYPES in agent_registry / GOVERNANCE.md.
VIOLATION_UNAUTHORIZED_TOOL = "unauthorized_tool"
VIOLATION_UNAUTHORIZED_PATH = "unauthorized_path"
VIOLATION_UNAUTHORIZED_OPERATION = "unauthorized_operation"
VIOLATION_RATE_LIMIT = "rate_limit"
VIOLATION_MISSING_CAPABILITY = "missing_capability"
VIOLATION_UNSAFE_NETWORK = "unsafe_network"


@dataclass
class ToolPolicy:
    """A single whitelisted tool and the constraints on its use."""

    name: str
    paths: list[str] = field(default_factory=list)  # glob patterns; empty = any
    operations: list[str] = field(default_factory=list)  # empty = any

    def allows_path(self, path: str) -> bool:
        """Allows path.

        Args:
            path (str): Filesystem or vault-relative path involved in the operation.

        Returns:
            bool: Boolean outcome for the requested check.
        """
        if not self.paths:
            return True
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.paths)

    def allows_operation(self, operation: str | None) -> bool:
        """Allows operation.

        Args:
            operation (Optional[str]): Operation name to validate or record.

        Returns:
            bool: Boolean outcome for the requested check.
        """
        if not self.operations:
            return True
        return operation in self.operations


@dataclass
class CheckResult:
    """Outcome of a sandbox permission check."""

    allowed: bool
    violation_type: str | None = None
    reason: str | None = None


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

    def __init__(
        self,
        agent_name,
        policies=None,
        registry=None,
        violation_recorder: Callable[[str, str, dict], dict] | None = None,
        capabilities: Iterable[str] | None = None,
    ):
        self.agent_name = agent_name
        self.registry = registry
        self.policies = {p.name: p for p in (policies or [])}
        self.violation_recorder = violation_recorder
        self.capabilities = set(capabilities or [])

    def check_dispatch(self, required_capability: str | None) -> CheckResult:
        """Validate governance state and capability before agent execution.

        Tool calls still use :meth:`check_action`; this preflight closes the
        production dispatch gap even for agents that do not yet expose an
        internal tool-call mediation hook.
        """
        if self.registry is not None and self.registry.is_quarantined(self.agent_name):
            return CheckResult(
                allowed=False,
                violation_type=None,
                reason="agent is quarantined",
            )
        if required_capability and required_capability not in self.capabilities:
            return self._deny(
                VIOLATION_MISSING_CAPABILITY,
                f"agent does not declare capability {required_capability!r}",
                {
                    "required_capability": required_capability,
                    "declared_capabilities": sorted(self.capabilities),
                },
            )
        return CheckResult(allowed=True)

    def check_action(
        self,
        tool_name: str,
        path: str | None = None,
        operation: str | None = None,
    ) -> CheckResult:
        """Check whether the agent may invoke the requested tool.

        Args:
            tool_name (str): Name of the tool being requested.
            path (Optional[str]): Optional path argument supplied with the tool call.
            operation (Optional[str]): Optional operation name supplied with the tool call.

        Returns:
            CheckResult: Permission decision for the requested sandbox action.
        """
        # A quarantined agent is denied everything until manually cleared.
        if self.registry is not None and self.registry.is_quarantined(self.agent_name):
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
                VIOLATION_UNAUTHORIZED_OPERATION,
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
            sanitize_for_log(self.agent_name),
            sanitize_for_log(violation_type),
            sanitize_for_log(reason),
        )
        if self.violation_recorder is not None:
            self.violation_recorder(self.agent_name, violation_type, details)
        elif self.registry is not None:
            self.registry.record_violation(self.agent_name, violation_type, details)
        return CheckResult(allowed=False, violation_type=violation_type, reason=reason)
