"""
Base agent abstract class for the Artemis-City MCP framework.

This module defines the BaseAgent abstract base class that all concrete agents
must inherit from. It follows JSF AV Rules 88-96 regarding inheritance and
the Liskov Substitution Principle.

Module Dependencies:
    - abc (standard library)
    - typing (standard library)
    - utils.helpers (internal logging)
    - types (internal type definitions)
    - exceptions (internal exception classes)

Thread Safety:
    BaseAgent instances are NOT thread-safe. Each agent should be used
    from a single thread, or external synchronization must be applied.

Author: Artemis-City Contributors
Date: 2024

Example:
    >>> from agents.base_agent import BaseAgent
    >>> from types import TaskContext, TaskResult
    >>>
    >>> class MyAgent(BaseAgent):
    ...     def perform_task(self, task_context: TaskContext) -> TaskResult:
    ...         self.report_status("Processing task...")
    ...         return {"status": "success", "summary": "Done"}
    >>>
    >>> agent = MyAgent("My Agent", capabilities=["analysis"])
    >>> result = agent.perform_task({"task_id": "1", "title": "Test"})
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

from utils.helpers import logger

if TYPE_CHECKING:
    from logging import Logger

    from types import TaskContext, TaskResult


class BaseAgent(ABC):
    """
    Abstract base class for all agents in the Artemis-City framework.

    This class defines the contract that all concrete agents must fulfill.
    It provides common functionality for logging and status reporting while
    requiring subclasses to implement the core task execution logic.

    Class Invariants:
        - name is always a non-empty string
        - capabilities is always a list (never None)
        - logger is always initialized and ready for use

    Attributes:
        name: Human-readable name identifying the agent.
        capabilities: List of capability strings this agent can handle.
        logger: Child logger for this specific agent instance.

    Inheritance Requirements (JSF AV Rule 92 - Liskov Substitution):
        All subclasses must:
        1. Implement perform_task() that accepts any valid TaskContext
        2. Return a valid TaskResult from perform_task()
        3. Not strengthen preconditions beyond what's documented
        4. Not weaken postconditions beyond what's documented
        5. Preserve the meaning of report_status() if overridden

    Example:
        >>> class ResearchAgent(BaseAgent):
        ...     def __init__(self):
        ...         super().__init__("Research Agent", ["research", "analysis"])
        ...
        ...     def perform_task(self, task_context: TaskContext) -> TaskResult:
        ...         query = task_context.get("query", "")
        ...         self.report_status(f"Researching: {query}")
        ...         # ... perform research ...
        ...         return {"status": "success", "summary": "Research complete"}
    """

    def __init__(
        self,
        name: str,
        capabilities: Optional[List[str]] = None,
    ) -> None:
        """
        Initialize a new agent instance.

        Args:
            name: Human-readable name for the agent. Must be non-empty.
                  Used for logging and identification in the agent registry.
            capabilities: List of capability strings this agent can handle.
                         Defaults to an empty list if not provided.
                         Used by the orchestrator for task routing.

        Raises:
            ValueError: If name is empty or None.

        Example:
            >>> agent = MyAgent("Analyzer", capabilities=["code_review"])
            >>> print(agent.name)
            Analyzer
            >>> print(agent.capabilities)
            ['code_review']
        """
        if not name or not name.strip():
            raise ValueError("Agent name must be a non-empty string")

        self.name: str = name
        self.capabilities: List[str] = capabilities if capabilities is not None else []
        self._logger: Logger = logger.getChild(self.name.replace(" ", "_"))
        self._logger.info(
            f"{self.name} initialized with capabilities: {self.capabilities}"
        )

    @property
    def logger(self) -> Logger:
        """Get the agent's logger instance."""
        return self._logger

    @abstractmethod
    def perform_task(self, task_context: dict) -> dict:
        """
        Execute a task and return the results.

        This is the core method that all concrete agents must implement.
        It receives a task context dictionary containing all information
        needed to execute the task, and returns a result dictionary.

        Args:
            task_context: Dictionary containing task information.
                Required keys vary by agent but typically include:
                - task_id: Unique identifier for the task
                - title: Human-readable task title
                - required_capability: The capability needed
                Optional keys may include:
                - content: Main task content/body
                - context: Additional contextual information
                - query: Search or lookup query

        Returns:
            Dictionary containing execution results with at minimum:
            - status: "success" or "failed"
            - summary: Human-readable summary of the result
            Additional keys depend on the specific agent.

        Raises:
            TaskExecutionError: If the task cannot be completed.
            TaskValidationError: If the task_context is invalid.

        Note:
            Implementations should call report_status() to provide
            progress updates during long-running tasks.

        Example:
            >>> result = agent.perform_task({
            ...     "task_id": "task_001",
            ...     "title": "Analyze module",
            ...     "content": "Review the orchestrator module",
            ... })
            >>> print(result["status"])
            success
        """
        pass

    def report_status(self, message: str) -> None:
        """
        Report agent progress or status.

        This method provides a standard way for agents to communicate
        their current status during task execution. Status messages
        are logged at INFO level.

        Args:
            message: Status message to report. Should be concise but
                    informative about the current operation.

        Example:
            >>> self.report_status("Parsing input documents...")
            >>> self.report_status("Analysis complete, generating summary")
        """
        self._logger.info(message)

    def validate_task_context(self, task_context: dict) -> bool:
        """
        Validate that a task context contains required fields.

        This helper method can be called by subclasses to perform
        basic validation before task execution.

        Args:
            task_context: The task context dictionary to validate.

        Returns:
            True if the context is valid, False otherwise.

        Example:
            >>> if not self.validate_task_context(task_context):
            ...     return {"status": "failed", "error": "Invalid context"}
        """
        if not isinstance(task_context, dict):
            return False
        # Basic validation - subclasses may add stricter checks
        return True

    def __repr__(self) -> str:
        """Return a string representation of the agent."""
        return f"{self.__class__.__name__}(name={self.name!r}, capabilities={self.capabilities!r})"
