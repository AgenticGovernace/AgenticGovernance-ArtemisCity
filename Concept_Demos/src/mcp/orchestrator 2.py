"""
MCP Orchestrator - Central coordination layer for agent task execution.

This module provides the Orchestrator class which serves as the central hub
for coordinating agent task execution within the Artemis-City framework.
It follows JSF AV Rules 1-3 for code complexity and AV Rules 70, 127, 185
for defensive programming.

Module Dependencies:
    - obsidian_integration: Vault management, parsing, generation
    - agents: Agent implementations (ArtemisAgent, ResearchAgent, etc.)
    - integration: Agent registry, governance, memory bus
    - mcp: Configuration, Hebbian learning, vector store

Thread Safety:
    The Orchestrator is NOT thread-safe. Concurrent task execution
    requires external synchronization.

Key Responsibilities:
    1. Agent registration and lifecycle management
    2. Task routing based on required capabilities
    3. Task execution with memory enrichment
    4. Hebbian learning for agent-task associations
    5. Obsidian vault integration for task persistence

Author: Artemis-City Contributors
Date: 2024

Example:
    >>> orchestrator = Orchestrator()
    >>> result = orchestrator.route_and_execute_task({
    ...     "task_id": "task_001",
    ...     "title": "Analyze codebase",
    ...     "required_capability": "system_management",
    ... })
    >>> print(result["status"])
    success
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ..agents.artemis_agent import ArtemisAgent
from ..agents.research_agent import ResearchAgent
from ..agents.summarizer_agent import SummarizerAgent
from ..exceptions import (
    AgentNotFoundError,
    MemoryBusError,
    TaskExecutionError,
    TaskRoutingError,
    TaskValidationError,
)
from ..integration.agent_registry import AgentRegistry
from ..integration.governance import GovernanceMonitor
from ..integration.memory_bus import MemoryBus
from ..mcp.config import AGENT_INPUT_DIR, AGENT_OUTPUT_DIR, OBSIDIAN_VAULT_PATH
from ..mcp.hebbian_weights import HebbianWeightManager
from ..mcp.vector_store import LocalVectorStore
from ..obsidian_integration.generator import ObsidianGenerator
from ..obsidian_integration.manager import ObsidianManager
from ..obsidian_integration.parser import ObsidianParser
from ..types import ExecutionSummary, TaskContext, TaskResult
from ..utils.helpers import logger

if TYPE_CHECKING:
    from ..agents.base_agent import BaseAgent

# Lazy import to avoid circular dependency
_run_logger = None


def _get_run_logger():
    """Lazy load run logger to avoid circular imports."""
    global _run_logger
    if _run_logger is None:
        try:
            from ..utils.run_logger import get_run_logger

            _run_logger = get_run_logger()
        except Exception:
            _run_logger = None
    return _run_logger


def _sanitize_for_log(value: Any) -> str:
    """Convert values to a single-line printable representation for logging."""
    text = str(value)
    return "".join(
        ch if ch.isprintable() and ch not in "\n\r\t" else " " for ch in text
    )


class Orchestrator:
    """
    Central coordination layer for agent task execution.

    The Orchestrator manages the complete lifecycle of task execution:
    routing tasks to appropriate agents, executing them with memory
    enrichment, and learning from outcomes via Hebbian weights.

    Class Invariants:
        - agent_registry is always initialized with at least one agent
        - obs_manager is connected to a valid Obsidian vault
        - All public methods return dict results with 'status' key

    Attributes:
        obs_manager: ObsidianManager for vault file operations.
        obs_parser: Parser for task note content.
        obs_generator: Generator for markdown output.
        hebbian: Hebbian weight manager for learning.
        vector_store: Local vector store for semantic search.
        governance_monitor: Monitor for failure tracking.
        memory_bus: Unified memory access layer.
        agent_registry: Registry of available agents.

    Example:
        >>> orchestrator = Orchestrator()
        >>> # Route and execute a task
        >>> result = orchestrator.route_and_execute_task({
        ...     "task_id": "t001",
        ...     "title": "Review code",
        ...     "required_capability": "system_management",
        ... })
        >>> # Execute all pending tasks from Obsidian
        >>> summary = orchestrator.execute_all_pending_tasks()
    """

    def __init__(self) -> None:
        """
        Initialize the Orchestrator with all required subsystems.

        Creates and configures:
        - Obsidian integration (manager, parser, generator)
        - Memory systems (vector store, memory bus)
        - Governance monitoring
        - Hebbian learning layer
        - Agent registry with default agents

        Raises:
            ObsidianConnectionError: If vault connection fails.
            ConfigurationError: If required config is missing.
        """
        # Obsidian integration components
        self.obs_manager = ObsidianManager(OBSIDIAN_VAULT_PATH)
        self.obs_parser = ObsidianParser()
        self.obs_generator = ObsidianGenerator()

        # Initialize Hebbian learning layer
        self.hebbian = HebbianWeightManager()

        # Initialize hybrid memory layer (vector + explicit Obsidian)
        self.vector_store = LocalVectorStore()
        self.governance_monitor = GovernanceMonitor()
        self.memory_bus = MemoryBus(
            self.obs_manager,
            self.vector_store,
            search_dirs=[AGENT_INPUT_DIR, AGENT_OUTPUT_DIR],
            governance_monitor=self.governance_monitor,
        )

        # Initialize Agent Registry
        self.agent_registry = AgentRegistry()
        self._register_agents()

        self._ensure_obsidian_agent_dirs()
        self._validate_kernel_state()
        logger.info("MCP Orchestrator initialized with Agent Registry.")

    def _register_agents(self) -> None:
        """
        Initialize and register all available agents.

        This method creates instances of all built-in agents and registers
        them with the agent registry. Called during Orchestrator initialization.

        Registered Agents:
            - ArtemisAgent: System management and coordination
            - ResearchAgent: Research and information gathering
            - SummarizerAgent: Content summarization
        """
        self.agent_registry.register_agent(ArtemisAgent())
        self.agent_registry.register_agent(ResearchAgent())
        self.agent_registry.register_agent(SummarizerAgent())
        logger.info(
            "All agent classes loaded and instances registered with the Agent Registry."
        )

    def _ensure_obsidian_agent_dirs(self):
        """Ensures the necessary Obsidian directories for agent interaction exist."""
        self.obs_manager.create_folder(AGENT_INPUT_DIR)
        self.obs_manager.create_folder(AGENT_OUTPUT_DIR)
        logger.info(
            "Ensured Obsidian agent input/output directories: %s, %s",
            _sanitize_for_log(AGENT_INPUT_DIR),
            _sanitize_for_log(AGENT_OUTPUT_DIR),
        )

    def _validate_kernel_state(self):
        """Validates kernel state and reports registered agents."""
        registered_agents = self.agent_registry.get_agent_names()
        if not registered_agents:
            logger.error("KERNEL ERROR: No agents registered in the registry!")
            return

        logger.info(
            "Kernel registered %s agent(s): %s",
            len(registered_agents),
            _sanitize_for_log(", ".join(registered_agents)),
        )

        # Verify each agent has required methods
        for agent_obj in self.agent_registry.get_all_agents():
            if not hasattr(agent_obj, "perform_task"):
                logger.warning(
                    "Agent '%s' missing 'perform_task' method",
                    _sanitize_for_log(agent_obj.name),
                )
            else:
                logger.debug("✓ %s validated", _sanitize_for_log(agent_obj.name))

    def _resolve_required_capability(
        self, task_context: Dict[str, Any]
    ) -> Optional[str]:
        """
        Resolve the required capability for a task.

        Attempts to determine the required capability by:
        1. Using the explicitly provided 'required_capability' field
        2. Inferring from the specified agent's primary capability

        Args:
            task_context: Task context dictionary that may contain
                         'required_capability' or 'agent' keys.

        Returns:
            The resolved capability string, or None if unable to resolve.

        Example:
            >>> cap = self._resolve_required_capability({"agent": "Artemis Agent"})
            >>> print(cap)  # Returns first capability of Artemis Agent
        """
        if not isinstance(task_context, dict):
            return None

        if task_context.get("required_capability"):
            return task_context["required_capability"]

        agent_name = task_context.get("agent")
        if agent_name:
            agent_obj = self.agent_registry.get_agent(agent_name)
            if agent_obj and agent_obj.capabilities:
                return agent_obj.capabilities[0]

        return None

    def route_and_execute_task(
        self,
        task_context: Dict[str, Any],
        original_task_note_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Route a task to the best agent and execute it.

        This method resolves the required capability, routes the task to
        an appropriate agent via the registry, and executes it.

        Args:
            task_context: Task context dictionary containing task details.
                         Must contain either 'required_capability' or 'agent'.
            original_task_note_path: Optional path to the Obsidian note
                                    to update with task status.

        Returns:
            Dictionary with execution results containing at minimum:
            - status: "success" or "failed"
            - summary: Human-readable result summary
            - error: Error message (if status is "failed")

        Raises:
            TaskRoutingError: If task cannot be routed to any agent.

        Example:
            >>> result = orchestrator.route_and_execute_task({
            ...     "task_id": "t001",
            ...     "required_capability": "research",
            ...     "content": "Research AI frameworks",
            ... })
        """
        try:
            resolved_capability = self._resolve_required_capability(task_context)
            if not resolved_capability:
                raise ValueError(
                    "Task dictionary must contain a 'required_capability' key or provide a known agent."
                )

            if task_context.get("required_capability") != resolved_capability:
                task_context = dict(task_context)
                task_context["required_capability"] = resolved_capability

            agent_name = self.agent_registry.route_task(task_context)
            logger.info("Task routed to '%s'.", _sanitize_for_log(agent_name))
            return self.assign_and_execute_task(
                agent_name, task_context, original_task_note_path
            )
        except (ValueError, KeyError) as e:
            logger.error("Task routing failed.", exc_info=True)
            if original_task_note_path:
                task_id = task_context.get("task_id", "unknown_task")
                self.update_task_status_in_obsidian(
                    original_task_note_path, "routing_failed", task_id
                )
            return {"status": "failed", "error": str(e)}

    def assign_and_execute_task(
        self,
        agent_name: str,
        task_context: Dict[str, Any],
        original_task_note_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Assign a task to a specific agent and execute it.

        This method handles the complete execution flow:
        1. Validate agent exists in registry
        2. Enrich task context with memory
        3. Execute task via agent.perform_task()
        4. Persist results to Obsidian vault
        5. Update Hebbian weights based on outcome
        6. Log execution metrics

        Args:
            agent_name: Name of the agent to assign the task to.
            task_context: Dictionary containing task details.
            original_task_note_path: Optional path to update status.

        Returns:
            Dictionary with execution results:
            - status: "success" or "failed"
            - summary: Human-readable result summary
            - error: Error message (if failed)
            Additional keys depend on the agent.

        Raises:
            AgentNotFoundError: If specified agent is not registered.
            TaskExecutionError: If task execution fails.

        Note:
            Hebbian learning is applied automatically - successful tasks
            strengthen agent-task associations, failures weaken them.
        """
        task_start_time = time.perf_counter()
        run_logger = _get_run_logger()

        agent = self.agent_registry.get_agent(agent_name)
        if not agent:
            logger.error("Agent '%s' not found in registry.", _sanitize_for_log(agent_name))
            raise ValueError(
                f"Agent '{agent_name}' not registered with the orchestrator."
            )

        logger.info("Orchestrator assigning task to %s...", _sanitize_for_log(agent_name))

        # Execute the task
        task_id = task_context.get("task_id", "auto_generated")
        task_success = False

        # Log task start
        if run_logger:
            run_logger.log_event(
                "task_start",
                "orchestrator",
                {
                    "task_id": task_id,
                    "agent": agent_name,
                    "capability": task_context.get("required_capability"),
                },
                f"Starting task {task_id} with {agent_name}",
            )

        try:
            enriched_context = self._enrich_task_with_memory(task_context)
            results = agent.perform_task(enriched_context)
            result_summary = results.get("summary", "N/A")
            logger.info(
                "Agent %s completed task. Results: %s",
                _sanitize_for_log(agent_name),
                _sanitize_for_log(result_summary),
            )

            # Determine if task was successful
            task_success = results.get("status") != "failed"

            # Write results via the memory bus for consistency and recall
            report_filename = (
                f"{agent_name.replace(' ', '_')}_Report_{task_id}_{len(results)}.md"
            )
            report_md = self.obs_generator.generate_agent_report(
                agent_name, task_id, results
            )
            report_path = f"{AGENT_OUTPUT_DIR}/{report_filename}"
            try:
                self.memory_bus.write_note_with_embedding(
                    report_path,
                    report_md,
                    metadata={"agent": agent_name, "task_id": task_id},
                )
            except Exception:
                logger.error(
                    "Failed to persist report for %s.",
                    _sanitize_for_log(agent_name),
                    exc_info=True,
                )

            # Update the original task note's status in Obsidian if provided
            if original_task_note_path:
                self.update_task_status_in_obsidian(
                    original_task_note_path, "completed", task_id
                )

        except Exception as e:
            logger.error(
                "Agent %s failed on task %s.",
                _sanitize_for_log(agent_name),
                _sanitize_for_log(task_id),
                exc_info=True,
            )
            task_success = False
            results = {
                "status": "failed",
                "error": str(e),
                "summary": f"Task failed: {e}",
            }

            # Update task status to failed
            if original_task_note_path:
                self.update_task_status_in_obsidian(
                    original_task_note_path, "failed", task_id
                )

        # Hebbian learning: Update connection weights based on success/failure
        self._update_hebbian_weights(agent_name, task_id, task_success)

        # Log task completion
        task_duration_ms = (time.perf_counter() - task_start_time) * 1000
        if run_logger:
            run_logger.log_task_execution(
                task_id=task_id,
                agent_name=agent_name,
                status="completed" if task_success else "failed",
                duration_ms=task_duration_ms,
                metadata={
                    "capability": task_context.get("required_capability"),
                    "summary": results.get("summary", "")[:100],
                },
            )

        return results

    def _update_hebbian_weights(self, agent_name: str, task_id: str, success: bool):
        """
        Update Hebbian connection weights based on task outcome.

        Args:
            agent_name: Name of the agent that executed the task
            task_id: ID of the task
            success: Whether the task succeeded
        """
        if success:
            new_weight = self.hebbian.strengthen_connection(agent_name, task_id)
            logger.info(
                "🧠 Hebbian: %s → %s strengthened (weight: %s)",
                _sanitize_for_log(agent_name),
                _sanitize_for_log(task_id),
                new_weight,
            )
        else:
            new_weight = self.hebbian.weaken_connection(agent_name, task_id)
            logger.info(
                "🧠 Hebbian: %s → %s weakened (weight: %s)",
                _sanitize_for_log(agent_name),
                _sanitize_for_log(task_id),
                new_weight,
            )

    def check_for_new_tasks_from_obsidian(self) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Scan the Obsidian input directory for new pending tasks.

        Reads all notes in AGENT_INPUT_DIR, parses them as task notes,
        and returns those with status "pending".

        Returns:
            List of tuples (relative_note_path, parsed_task_data) for
            all pending tasks found. Empty list if none found.

        Example:
            >>> tasks = orchestrator.check_for_new_tasks_from_obsidian()
            >>> for path, task_data in tasks:
            ...     print(f"Found task: {task_data['title']}")
        """
        logger.info(
            "Checking for new tasks in Obsidian folder: %s",
            _sanitize_for_log(AGENT_INPUT_DIR),
        )
        input_notes = self.obs_manager.list_notes_in_folder(AGENT_INPUT_DIR)

        new_tasks = []
        for note_filename in input_notes:
            relative_path = os.path.join(AGENT_INPUT_DIR, note_filename)
            content = self.obs_manager.read_note(relative_path)
            if content:
                task_data = self.obs_parser.parse_task_note(content)
                if (
                    task_data
                    and task_data.get("status", "pending").lower() == "pending"
                ):
                    task_data["task_id"] = task_data.get(
                        "task_id", f"task_{hash(note_filename) % 100000}"
                    )  # Generate ID if missing
                    resolved_capability = self._resolve_required_capability(task_data)
                    if resolved_capability:
                        task_data["required_capability"] = resolved_capability
                    logger.info(
                        "Found new pending task: '%s' for agent '%s'",
                        _sanitize_for_log(task_data.get("title", note_filename)),
                        _sanitize_for_log(task_data.get("agent")),
                    )
                    new_tasks.append((relative_path, task_data))
                else:
                    logger.debug(
                        "Note '%s' is not a pending task or couldn't be parsed.",
                        _sanitize_for_log(note_filename),
                    )

        return new_tasks

    def update_task_status_in_obsidian(
        self, relative_note_path: str, new_status: str, task_id: str = None
    ):
        """
        Updates the status of a specific task note in Obsidian.
        """
        logger.info(
            "Updating status for task note '%s' to '%s'",
            _sanitize_for_log(relative_note_path),
            _sanitize_for_log(new_status),
        )
        original_content = self.obs_manager.read_note(relative_note_path)
        if original_content:
            updated_content = self.obs_parser.update_status_in_note(
                original_content, new_status, task_id
            )
            try:
                self.memory_bus.write_note_with_embedding(
                    relative_note_path,
                    updated_content,
                    metadata={"task_id": task_id, "status": new_status},
                )
            except Exception:
                logger.error(
                    "Memory bus write failed for %s.",
                    _sanitize_for_log(relative_note_path),
                    exc_info=True,
                )
                self.obs_manager.write_note(relative_note_path, updated_content)
            logger.info(
                "Status updated for '%s' to '%s'.",
                _sanitize_for_log(relative_note_path),
                _sanitize_for_log(new_status),
            )
        else:
            logger.warning(
                "Could not read original content for '%s' to update status.",
                _sanitize_for_log(relative_note_path),
            )

    def create_new_task_in_obsidian(
        self, task_data: dict, filename: str | None = None
    ) -> str:
        """
        Creates a new task note in the AGENT_INPUT_DIR of Obsidian.
        Returns the relative path to the new note.
        """
        task_title = task_data.get("title", "new_agent_task")
        resolved_capability = self._resolve_required_capability(task_data)
        if resolved_capability:
            task_data = dict(task_data)
            task_data["required_capability"] = resolved_capability
        else:
            logger.warning(
                "No required_capability provided or inferred for task '%s'. Task may not be routed correctly.",
                _sanitize_for_log(task_title),
            )

        if not filename:
            title_slug = task_title.lower().replace(" ", "_")
            filename = f"{title_slug}_{datetime.now().strftime('%Y%m%d%H%M%S')}.md"

        relative_path = os.path.join(AGENT_INPUT_DIR, filename)
        markdown_content = self.obs_generator.generate_task_note(task_data)
        try:
            self.memory_bus.write_note_with_embedding(
                relative_path,
                markdown_content,
                metadata={
                    "task_id": task_data.get("task_id"),
                    "created_by": "orchestrator",
                },
            )
        except Exception:
            logger.error(
                "Failed to persist new task to memory bus for %s.",
                _sanitize_for_log(relative_path),
                exc_info=True,
            )
            self.obs_manager.write_note(relative_path, markdown_content)
        logger.info(
            "Created new task note in Obsidian: %s",
            _sanitize_for_log(relative_path),
        )
        return relative_path

    def execute_all_pending_tasks(self) -> dict:
        """
        Executes every pending task discovered in the Obsidian input directory.
        Returns a summary with counts and per-task results.
        """
        pending_tasks = self.check_for_new_tasks_from_obsidian()
        summary = {
            "total": len(pending_tasks),
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
        }

        if not pending_tasks:
            logger.info("No pending tasks found to execute.")
            return summary

        logger.info("Executing %s pending task(s) from Obsidian.", len(pending_tasks))

        for relative_note_path, task_data in pending_tasks:
            task_id = task_data.get("task_id", "unknown_task")
            capability = self._resolve_required_capability(task_data)
            if capability:
                task_data["required_capability"] = capability
            else:
                logger.warning(
                    "Skipping task %s at %s: no required_capability found or inferred.",
                    _sanitize_for_log(task_id),
                    _sanitize_for_log(relative_note_path),
                )
                self.update_task_status_in_obsidian(
                    relative_note_path, "no_capability", task_id
                )
                summary["skipped"] += 1
                summary["details"].append(
                    {"task_id": task_id, "status": "skipped", "reason": "no_capability"}
                )
                continue

            try:
                self.update_task_status_in_obsidian(
                    relative_note_path, "in progress", task_id
                )
                self.route_and_execute_task(task_data, relative_note_path)
                summary["completed"] += 1
                summary["details"].append({"task_id": task_id, "status": "completed"})
            except Exception as exc:
                logger.error(
                    "Failed to execute task %s from %s.",
                    _sanitize_for_log(task_id),
                    _sanitize_for_log(relative_note_path),
                    exc_info=True,
                )
                self.update_task_status_in_obsidian(
                    relative_note_path, "failed", task_id
                )
                summary["failed"] += 1
                summary["details"].append(
                    {"task_id": task_id, "status": "failed", "error": str(exc)}
                )

        return summary

    def _enrich_task_with_memory(self, task_context: dict) -> dict:
        """
        Pull contextual memory for the task using the memory bus read hierarchy.
        """
        query = (
            task_context.get("content")
            or task_context.get("context")
            or task_context.get("title")
            or ""
        )
        if not query:
            return task_context

        try:
            retrievals = self.memory_bus.read(query, max_results=3)
        except Exception:
            logger.error(
                "Memory bus read failed for task %s.",
                _sanitize_for_log(task_context.get("task_id")),
                exc_info=True,
            )
            return task_context

        if not retrievals:
            return task_context

        enriched = dict(task_context)
        enriched["memory_context"] = retrievals
        return enriched

    def show_hebbian_network_summary(self):
        """
        Display Hebbian network statistics.
        """
        summary = self.hebbian.get_network_summary()
        logger.info("\n" + "=" * 60)
        logger.info("🧠 HEBBIAN LEARNING NETWORK SUMMARY")
        logger.info("=" * 60)
        logger.info("Total Connections: %s", summary.get("total_connections", 0))
        logger.info("Average Weight: %.2f", summary.get("average_weight", 0))
        logger.info("Max Weight: %.2f", summary.get("max_weight", 0))
        logger.info("Total Activations: %s", summary.get("total_activations", 0))
        logger.info("Success Rate: %.2f%%", summary.get("success_rate", 0) * 100)
        logger.info("=" * 60 + "\n")

    def show_agent_hebbian_stats(self, agent_name: str):
        """Display Hebbian statistics for a specific agent."""
        avg_weight = self.hebbian.get_agent_average_weight(agent_name)
        success_rate = self.hebbian.get_agent_success_rate(agent_name)
        connections = self.hebbian.get_strongest_connections(agent_name, limit=10)

        logger.info("\n" + "=" * 60)
        logger.info("🧠 HEBBIAN STATS FOR: %s", _sanitize_for_log(agent_name))
        logger.info("=" * 60)
        logger.info("Average Weight: %.2f", avg_weight)
        logger.info("Success Rate: %.2f%%", success_rate * 100)
        logger.info("\nStrongest Connections:")
        for i, (target, weight) in enumerate(connections, 1):
            logger.info(
                "  %s. %s (weight: %.1f)",
                i,
                _sanitize_for_log(target),
                weight,
            )
        logger.info("=" * 60 + "\n")
