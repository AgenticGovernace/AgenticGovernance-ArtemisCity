"""
Custom exception hierarchy for the Artemis-City MCP framework.

This module defines domain-specific exceptions following JSF AV Rules 208 and 217,
which emphasize structured error handling and compile-time error detection where possible.

Exception Hierarchy:
    ArtemisError (base)
    ├── TaskError
    │   ├── TaskRoutingError
    │   ├── TaskExecutionError
    │   └── TaskValidationError
    ├── AgentError
    │   ├── AgentNotFoundError
    │   ├── AgentRegistrationError
    │   └── AgentCapabilityError
    ├── MemoryError
    │   ├── MemoryBusError
    │   ├── VectorStoreError
    │   └── ObsidianConnectionError
    └── GovernanceError
        ├── GovernanceViolationError
        └── GovernanceThresholdError

Usage:
    from exceptions import TaskRoutingError, AgentNotFoundError

    try:
        agent = registry.get_agent(name)
        if agent is None:
            raise AgentNotFoundError(name)
    except AgentNotFoundError as e:
        logger.error(f"Agent lookup failed: {e}")

Author: Artemis-City Contributors
Date: 2024
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ArtemisError(Exception):
    """
    Base exception for all Artemis-City framework errors.

    All custom exceptions in the framework inherit from this class,
    allowing for broad exception catching when needed while still
    supporting specific exception handling.

    Attributes:
        message: Human-readable error description.
        error_code: Optional error code for programmatic handling.
        details: Optional dictionary with additional context.

    Example:
        >>> raise ArtemisError("Operation failed", error_code="E001")
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        result: Dict[str, Any] = {
            "error": self.__class__.__name__,
            "message": self.message,
        }
        if self.error_code:
            result["error_code"] = self.error_code
        if self.details:
            result["details"] = self.details
        return result


# =============================================================================
# Task-Related Exceptions
# =============================================================================


class TaskError(ArtemisError):
    """Base exception for task-related errors."""

    pass


class TaskRoutingError(TaskError):
    """
    Raised when a task cannot be routed to an appropriate agent.

    This typically occurs when:
    - No agent has the required capability
    - The required_capability field is missing
    - Multiple agents conflict on routing priority

    Attributes:
        task_id: The ID of the task that failed routing.
        required_capability: The capability that was requested.
    """

    def __init__(
        self,
        message: str,
        task_id: Optional[str] = None,
        required_capability: Optional[str] = None,
    ) -> None:
        details = {}
        if task_id:
            details["task_id"] = task_id
        if required_capability:
            details["required_capability"] = required_capability
        super().__init__(message, error_code="TASK_ROUTE_001", details=details)
        self.task_id = task_id
        self.required_capability = required_capability


class TaskExecutionError(TaskError):
    """
    Raised when a task fails during execution.

    Attributes:
        task_id: The ID of the task that failed.
        agent_name: The agent that was executing the task.
        original_error: The underlying exception, if any.
    """

    def __init__(
        self,
        message: str,
        task_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        if task_id:
            details["task_id"] = task_id
        if agent_name:
            details["agent_name"] = agent_name
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(message, error_code="TASK_EXEC_001", details=details)
        self.task_id = task_id
        self.agent_name = agent_name
        self.original_error = original_error


class TaskValidationError(TaskError):
    """
    Raised when task context validation fails.

    Attributes:
        task_id: The ID of the invalid task.
        missing_fields: List of required fields that are missing.
        invalid_fields: Dict of fields with invalid values.
    """

    def __init__(
        self,
        message: str,
        task_id: Optional[str] = None,
        missing_fields: Optional[List[str]] = None,
        invalid_fields: Optional[Dict[str, str]] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        if task_id:
            details["task_id"] = task_id
        if missing_fields:
            details["missing_fields"] = missing_fields
        if invalid_fields:
            details["invalid_fields"] = invalid_fields
        super().__init__(message, error_code="TASK_VALID_001", details=details)
        self.task_id = task_id
        self.missing_fields = missing_fields or []
        self.invalid_fields = invalid_fields or {}


# =============================================================================
# Agent-Related Exceptions
# =============================================================================


class AgentError(ArtemisError):
    """Base exception for agent-related errors."""

    pass


class AgentNotFoundError(AgentError):
    """
    Raised when a requested agent is not found in the registry.

    Attributes:
        agent_name: The name of the agent that was not found.
        available_agents: List of agents that are available.
    """

    def __init__(
        self,
        agent_name: str,
        available_agents: Optional[List[str]] = None,
    ) -> None:
        message = f"Agent '{agent_name}' not found in registry"
        details: Dict[str, Any] = {"agent_name": agent_name}
        if available_agents:
            details["available_agents"] = available_agents
            message += f". Available: {', '.join(available_agents)}"
        super().__init__(message, error_code="AGENT_NOT_FOUND", details=details)
        self.agent_name = agent_name
        self.available_agents = available_agents or []


class AgentRegistrationError(AgentError):
    """
    Raised when agent registration fails.

    Attributes:
        agent_name: The name of the agent that failed to register.
        reason: The reason for registration failure.
    """

    def __init__(self, agent_name: str, reason: str) -> None:
        message = f"Failed to register agent '{agent_name}': {reason}"
        super().__init__(
            message,
            error_code="AGENT_REG_001",
            details={"agent_name": agent_name, "reason": reason},
        )
        self.agent_name = agent_name
        self.reason = reason


class AgentCapabilityError(AgentError):
    """
    Raised when an agent lacks a required capability.

    Attributes:
        agent_name: The name of the agent.
        required_capability: The capability that was required.
        agent_capabilities: The capabilities the agent actually has.
    """

    def __init__(
        self,
        agent_name: str,
        required_capability: str,
        agent_capabilities: Optional[List[str]] = None,
    ) -> None:
        message = (
            f"Agent '{agent_name}' lacks required capability '{required_capability}'"
        )
        details: Dict[str, Any] = {
            "agent_name": agent_name,
            "required_capability": required_capability,
        }
        if agent_capabilities:
            details["agent_capabilities"] = agent_capabilities
        super().__init__(message, error_code="AGENT_CAP_001", details=details)
        self.agent_name = agent_name
        self.required_capability = required_capability
        self.agent_capabilities = agent_capabilities or []


# =============================================================================
# Memory-Related Exceptions
# =============================================================================


class MemorySystemError(ArtemisError):
    """Base exception for memory system errors."""

    pass


class MemoryBusError(MemorySystemError):
    """
    Raised when memory bus operations fail.

    Attributes:
        operation: The operation that failed (read, write, sync).
        path: The path involved in the operation, if any.
    """

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        path: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        if operation:
            details["operation"] = operation
        if path:
            details["path"] = path
        super().__init__(message, error_code="MEM_BUS_001", details=details)
        self.operation = operation
        self.path = path


class VectorStoreError(MemorySystemError):
    """
    Raised when vector store operations fail.

    Attributes:
        operation: The operation that failed.
        query: The query that caused the failure, if any.
    """

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        query: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        if operation:
            details["operation"] = operation
        if query:
            details["query"] = query[:100] if query else None  # Truncate for safety
        super().__init__(message, error_code="VEC_STORE_001", details=details)
        self.operation = operation
        self.query = query


class ObsidianConnectionError(MemorySystemError):
    """
    Raised when connection to Obsidian vault fails.

    Attributes:
        vault_path: The path to the Obsidian vault.
        reason: The reason for connection failure.
    """

    def __init__(self, vault_path: str, reason: str) -> None:
        message = f"Failed to connect to Obsidian vault at '{vault_path}': {reason}"
        super().__init__(
            message,
            error_code="OBS_CONN_001",
            details={"vault_path": vault_path, "reason": reason},
        )
        self.vault_path = vault_path
        self.reason = reason


# =============================================================================
# Governance-Related Exceptions
# =============================================================================


class GovernanceError(ArtemisError):
    """Base exception for governance-related errors."""

    pass


class GovernanceViolationError(GovernanceError):
    """
    Raised when a governance policy is violated.

    Attributes:
        policy: The policy that was violated.
        violation_details: Specific details about the violation.
    """

    def __init__(
        self,
        message: str,
        policy: Optional[str] = None,
        violation_details: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        if policy:
            details["policy"] = policy
        if violation_details:
            details["violation_details"] = violation_details
        super().__init__(message, error_code="GOV_VIOL_001", details=details)
        self.policy = policy
        self.violation_details = violation_details


class GovernanceThresholdError(GovernanceError):
    """
    Raised when a governance threshold is exceeded.

    Attributes:
        threshold_name: Name of the threshold that was exceeded.
        threshold_value: The configured threshold value.
        actual_value: The actual value that exceeded the threshold.
    """

    def __init__(
        self,
        message: str,
        threshold_name: str,
        threshold_value: int,
        actual_value: int,
    ) -> None:
        super().__init__(
            message,
            error_code="GOV_THRESH_001",
            details={
                "threshold_name": threshold_name,
                "threshold_value": threshold_value,
                "actual_value": actual_value,
            },
        )
        self.threshold_name = threshold_name
        self.threshold_value = threshold_value
        self.actual_value = actual_value


# =============================================================================
# Configuration Exceptions
# =============================================================================


class ConfigurationError(ArtemisError):
    """
    Raised when configuration is invalid or missing.

    Attributes:
        config_key: The configuration key that is invalid/missing.
        expected_type: The expected type of the configuration value.
    """

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        expected_type: Optional[str] = None,
    ) -> None:
        details: Dict[str, Any] = {}
        if config_key:
            details["config_key"] = config_key
        if expected_type:
            details["expected_type"] = expected_type
        super().__init__(message, error_code="CONFIG_001", details=details)
        self.config_key = config_key
        self.expected_type = expected_type
