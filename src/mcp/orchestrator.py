import hashlib
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.agents import SummarizerAgent
from src.agents.artemis_agent import ArtemisAgent
from src.agents.llm_agent import LLMAgent
from src.agents.research_agent import ResearchAgent
from src.agents.atp.atp_context import resolve_task_context
from src.obsidian_integration import ObsidianGenerator, ObsidianManager, ObsidianParser
from src.utils.helpers import logger, sanitize_for_log
from src.governance.checkpoints import CheckpointStore

from ..integration.agent_registry import AgentRegistry
from ..integration.governance import GovernanceMonitor
from ..integration.hebbian_router import HebbianRouter
from ..integration.learning_governance import LearningGovernanceCoordinator
from ..integration.memory_bus import MemoryBus
from ..integration.memory_decay import MemoryDecayService
from ..integration.sandbox import AgentSandbox
from ..mcp.config import AGENT_INPUT_DIR, AGENT_OUTPUT_DIR, OBSIDIAN_VAULT_PATH
from ..mcp.hebbian_weights import HebbianWeightManager
from ..mcp.vector_store import LocalVectorStore

# Lazy import to avoid circular dependency
_run_logger = None


def _get_run_logger():
    """Lazy load run logger to avoid circular imports."""
    global _run_logger
    if _run_logger is None:
        try:
            from src.utils import get_run_logger

            _run_logger = get_run_logger()
        except Exception:
            _run_logger = None
    return _run_logger


def _sanitize_for_log(value: Any) -> str:
    """Convert values to a single-line printable representation for logging.

    Thin wrapper around the shared ``src.utils.helpers.sanitize_for_log``
    so every module applies the same CodeQL-recognized log-injection
    sanitizer (``.replace`` chain + printable whitelist + truncation).
    Kept under the historical private name to avoid churning the ~40
    call sites in this module.
    """
    return sanitize_for_log(value)


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
        memory_decay_enabled = os.getenv(
            "ARTEMIS_MEMORY_DECAY_ENABLED", "1"
        ).strip().lower() not in ("0", "false", "no", "off")
        self.memory_decay_service = (
            MemoryDecayService() if memory_decay_enabled else None
        )
        self.memory_bus = MemoryBus(
            self.obs_manager,
            self.vector_store,
            search_dirs=[AGENT_INPUT_DIR, AGENT_OUTPUT_DIR],
            governance_monitor=self.governance_monitor,
            memory_decay_service=self.memory_decay_service,
        )
        if self.memory_decay_service is not None:
            try:
                self.memory_bus.run_memory_decay_cycle()
            except Exception:  # noqa: BLE001
                logger.warning("Memory decay cycle failed during boot.", exc_info=True)

        # Initialize Agent Registry
        self.agent_registry = AgentRegistry()
        self._register_agents()

        # Hebbian-weighted routing: bias agent selection by learned agent->task
        # success. Disable with ARTEMIS_HEBBIAN_ROUTING=0; tune the blend with
        # ARTEMIS_HEBBIAN_ROUTING_ALPHA  (weight on Hebbian, default 0.3)
        # and ARTEMIS_HEBBIAN_ROUTING_BETA (weight on trust,   default 0.0).
        # Composite weight is (1 - alpha - beta). Exclude agents below
        # ARTEMIS_ROUTING_TRUST_FLOOR (default 0.0 = disabled).
        self.hebbian_routing_enabled = os.getenv(
            "ARTEMIS_HEBBIAN_ROUTING", "1"
        ).strip().lower() not in ("0", "false", "no", "off")

        def _env_float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except ValueError:
                return default

        _routing_alpha = _env_float("ARTEMIS_HEBBIAN_ROUTING_ALPHA", 0.3)
        _routing_beta = _env_float("ARTEMIS_HEBBIAN_ROUTING_BETA", 0.0)
        _routing_trust_floor = _env_float("ARTEMIS_ROUTING_TRUST_FLOOR", 0.0)

        # Unmatched / unspecified tasks fall back to the general-purpose LLM
        # capability (set ARTEMIS_ROUTING_FALLBACK_CAPABILITY="" to disable).
        _fallback_cap = (
            os.getenv("ARTEMIS_ROUTING_FALLBACK_CAPABILITY", "llm_chat").strip() or None
        )

        # Trust persistence is part of every execution outcome even when beta
        # is zero and trust does not affect routing. Construction remains a
        # soft dependency so a damaged optional store cannot block boot.
        self.trust_interface = None
        try:
            from ..integration.trust_interface import TrustInterface

            self.trust_interface = TrustInterface()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Trust persistence unavailable (continuing without trust signal): %s",
                exc,
            )
            _routing_beta = 0.0
            _routing_trust_floor = 0.0

        self.hebbian_router = HebbianRouter(
            self.agent_registry,
            self.hebbian,
            alpha=_routing_alpha,
            fallback_capability=_fallback_cap,
            trust_interface=self.trust_interface,
            beta=_routing_beta,
            trust_floor=_routing_trust_floor,
        )
        self.learning_governance = LearningGovernanceCoordinator(
            self.agent_registry,
            trust_interface=self.trust_interface,
            hebbian_manager=self.hebbian,
            checkpoint_store=CheckpointStore(),
        )
        for registered_agent in self.agent_registry.get_all_agents():
            self.learning_governance.reconcile_agent(registered_agent.name)

        # Initialize and migrate the shared audit/provenance sink at boot so
        # dashboard reads never race the first task write.
        if _get_run_logger() is None:
            logger.warning("Run provenance sink is unavailable at boot.")

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
            - LLMAgent: LLM inference over the configured EXO endpoint

        Anaconda Agent Studio integration:
            After in-process agents are registered, the orchestrator
            attempts to register any running Anaconda Agent Studio
            agents from the stack at ~/Source/artemis-agent-stack/.
            Integration is opt-in via ``ANACONDA_AGENT_PORTS`` in
            ``src/.env``; when that var is empty (the default), this is
            a no-op and the in-process agents alone serve traffic.
        """
        self.agent_registry.register_agent(ArtemisAgent())
        self.agent_registry.register_agent(ResearchAgent())
        self.agent_registry.register_agent(SummarizerAgent())
        self.agent_registry.register_agent(LLMAgent())

        # Bridge in any running Anaconda Agent Studio agents. Failures
        # here must NEVER block orchestrator startup -- the helper
        # already swallows discovery errors, but defend in depth.
        try:
            from src.integration.anaconda_stack import register_anaconda_stack

            registered_anaconda = register_anaconda_stack(self.agent_registry)
            if registered_anaconda:
                logger.info(
                    "Anaconda Agent Studio agents registered: %s",
                    ", ".join(registered_anaconda),
                )
        except ModuleNotFoundError as exc:
            if exc.name == "requests":
                logger.info(
                    "Skipping optional Anaconda Agent Studio integration: "
                    "the 'requests' package is not installed."
                )
            else:
                logger.warning(
                    "Anaconda Agent Studio integration failed "
                    "(continuing without it): %s",
                    exc,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Anaconda Agent Studio integration failed (continuing without it): %s",
                exc,
            )

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

    def prepare_task_context(self, task_context: Dict[str, Any]) -> Dict[str, Any]:
        """Attach canonical ATP routing context when headers are present."""
        strict_default = os.getenv("ARTEMIS_ATP_STRICT", "0").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        strict = bool(task_context.get("atp_strict", strict_default))
        return resolve_task_context(
            task_context,
            strict=strict,
            default_capability=self.hebbian_router.fallback_capability or "llm_chat",
        )

    @staticmethod
    def _strict_provenance(task_context: Dict[str, Any]) -> bool:
        """ATP prompts fail closed when their provenance sink is unavailable."""
        return bool(task_context.get("atp"))

    def ensure_task_provenance(
        self,
        task_context: Dict[str, Any],
        *,
        source: str,
    ) -> Dict[str, Any]:
        """Create the parent provenance event for one prompt/task."""
        if task_context.get("provenance_id"):
            return task_context

        parent_id = str(uuid.uuid4())
        run_logger = _get_run_logger()
        if run_logger is None:
            if self._strict_provenance(task_context):
                raise RuntimeError("ATP provenance sink is unavailable")
            task_context["provenance_id"] = parent_id
            return task_context

        prompt = str(task_context.get("atp_raw") or task_context.get("content") or "")
        recorded_id = run_logger.log_event(
            "prompt_received",
            "orchestrator",
            {
                "task_id": task_context.get("task_id"),
                "source": source,
                "required_capability": task_context.get("required_capability"),
                "routing_scope": task_context.get("routing_scope"),
                "atp": task_context.get("atp"),
                "content_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            },
            "Prompt accepted for governed routing",
            prov_id=parent_id,
        )
        task_context["provenance_id"] = recorded_id
        return task_context

    def _log_provenance_action(
        self,
        task_context: Dict[str, Any],
        event_type: str,
        component: str,
        metadata: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> Optional[str]:
        """Write one child action linked to the task's parent provenance."""
        parent_id = task_context.get("provenance_id")
        if not parent_id:
            self.ensure_task_provenance(task_context, source=component)
            parent_id = task_context.get("provenance_id")
        run_logger = _get_run_logger()
        if run_logger is None:
            if self._strict_provenance(task_context):
                raise RuntimeError("ATP provenance sink is unavailable")
            return None
        return run_logger.log_event(
            event_type,
            component,
            metadata,
            message,
            duration_ms,
            parent_prov_id=str(parent_id),
        )

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
            task_context = self.prepare_task_context(task_context)
            task_context = self.ensure_task_provenance(
                task_context,
                source="route_and_execute_task",
            )
            resolved_capability = self._resolve_required_capability(task_context)
            if not resolved_capability:
                raise ValueError(
                    "Task dictionary must contain a 'required_capability' key or provide a known agent."
                )

            if task_context.get("required_capability") != resolved_capability:
                task_context = dict(task_context)
                task_context["required_capability"] = resolved_capability

            decision = None
            if self.hebbian_routing_enabled:
                decision = self.hebbian_router.route(task_context)
                agent_name = decision.agent_name
            else:
                agent_name = self.agent_registry.route_task(task_context)
            self.log_routing_decision(
                task_context,
                agent_name,
                decision=decision,
                source="route_and_execute_task",
            )
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
        task_context = self.prepare_task_context(task_context)
        task_context = self.ensure_task_provenance(
            task_context,
            source="assign_and_execute_task",
        )
        task_start_time = time.perf_counter()
        run_logger = _get_run_logger()

        agent = self.agent_registry.get_agent(agent_name)
        if not agent:
            logger.error(
                "Agent '%s' not found in registry.", _sanitize_for_log(agent_name)
            )
            raise ValueError(
                f"Agent '{agent_name}' not registered with the orchestrator."
            )

        sandbox_result = self._check_dispatch(agent, task_context)
        if not sandbox_result.allowed:
            task_id = task_context.get("task_id", "auto_generated")
            result = {
                "status": "failed",
                "summary": "Task denied by governance policy.",
                "error": sandbox_result.reason or "sandbox denied dispatch",
                "governance": {
                    "allowed": False,
                    "violation_type": sandbox_result.violation_type,
                },
            }
            if original_task_note_path:
                self.update_task_status_in_obsidian(
                    original_task_note_path,
                    "failed",
                    task_id,
                )
            self._log_provenance_action(
                task_context,
                "dispatch_denied",
                "sandbox",
                {
                    "task_id": task_id,
                    "agent": agent_name,
                    "capability": task_context.get("required_capability"),
                    "violation_type": sandbox_result.violation_type,
                    "reason": sandbox_result.reason,
                },
            )
            return result

        logger.info(
            "Orchestrator assigning task to %s...", _sanitize_for_log(agent_name)
        )

        # Execute the task
        task_id = task_context.get("task_id", "auto_generated")
        task_success = False

        # Log task start
        self._log_provenance_action(
            task_context,
            "task_start",
            "orchestrator",
            {
                "task_id": task_id,
                "agent": agent_name,
                "capability": task_context.get("required_capability"),
                "routing_scope": task_context.get("routing_scope"),
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
                    metadata={
                        "agent": agent_name,
                        "task_id": task_id,
                        "provenance_id": task_context.get("provenance_id"),
                        "routing_scope": task_context.get("routing_scope"),
                        "atp_action_type": task_context.get("atp_action_type"),
                    },
                )
                self._log_provenance_action(
                    task_context,
                    "memory_persisted",
                    "memory_bus",
                    {"task_id": task_id, "path": report_path},
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
                    original_task_note_path,
                    "completed" if task_success else "failed",
                    task_id,
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

        task_duration_ms = (time.perf_counter() - task_start_time) * 1000

        # Full learning update: nonlinear Hebbian/anti-Hebbian weight,
        # pair/timing signals, registry mirror, and governance trust score.
        learning = self._update_hebbian_weights(
            agent_name,
            task_id,
            task_success,
            task_type=(
                task_context.get("routing_scope")
                or task_context.get("required_capability")
            ),
            results=results,
            duration_ms=task_duration_ms,
        )
        self._log_provenance_action(
            task_context,
            "learning_updated",
            "hebbian_weights",
            {
                "task_id": task_id,
                "agent": agent_name,
                "task_type": learning.get("task_type"),
                "delta": learning.get("delta"),
                "weight": learning.get("weight"),
                "sentinel_alert": learning.get("sentinel_alert", False),
            },
        )

        results.setdefault("provenance_id", task_context.get("provenance_id"))
        if task_context.get("atp"):
            results.setdefault("atp", task_context["atp"])

        # Log task completion
        if run_logger:
            run_logger.log_task_execution(
                task_id=task_id,
                agent_name=agent_name,
                status="completed" if task_success else "failed",
                duration_ms=task_duration_ms,
                metadata={
                    "capability": task_context.get("required_capability"),
                    "routing_scope": task_context.get("routing_scope"),
                    "summary": results.get("summary", "")[:100],
                },
                parent_prov_id=task_context.get("provenance_id"),
            )

        return results

    def stream_route_and_execute(
        self,
        task_context: Dict[str, Any],
        original_task_note_path: Optional[str] = None,
    ):
        """Stream a routing + execution flow as a sequence of events.

        Yields dicts in this order:
            {"type": "routing",  "decision": {...}}
            {"type": "token",    "text": "..."}     # zero or more
            {"type": "complete", "task_id": ..., "agent_name": ..., "summary": ..., "note_path": ...}
        or on failure:
            {"type": "error", "error": "..."}

        Agents that expose ``supports_streaming = True`` and a ``stream_task``
        method (currently only ``LLMAgent``) drive the ``token`` events
        directly. Agents without streaming are still routed through this
        path — they execute synchronously and emit a single ``token`` event
        with the full summary, so the client UI does not need to special-
        case which agent was picked.
        """
        try:
            task_context = self.prepare_task_context(task_context)
            task_context = self.ensure_task_provenance(
                task_context,
                source="stream_route_and_execute",
            )
            resolved_capability = self._resolve_required_capability(task_context)
            if not resolved_capability:
                yield {
                    "type": "error",
                    "error": "Task dictionary must contain a 'required_capability' "
                    "or provide a known agent.",
                }
                return

            if task_context.get("required_capability") != resolved_capability:
                task_context = dict(task_context)
                task_context["required_capability"] = resolved_capability

            # Resolve the agent: either user-pinned, or the Hebbian decision.
            explicit_agent = task_context.get("agent")
            decision = None
            if explicit_agent:
                agent_name = explicit_agent
            elif self.hebbian_routing_enabled:
                decision = self.hebbian_router.route(task_context)
                agent_name = decision.agent_name
            else:
                agent_name = self.agent_registry.route_task(task_context)

            self.log_routing_decision(
                task_context,
                agent_name,
                decision=decision,
                source="stream_route_and_execute",
                pinned=bool(explicit_agent),
            )

            yield {
                "type": "routing",
                "decision": decision.to_dict() if decision else None,
                "agent_name": agent_name,
            }
        except (ValueError, KeyError) as exc:
            logger.error(
                "Stream routing failed: %s", _sanitize_for_log(exc), exc_info=True
            )
            # The streaming endpoint already created the Obsidian note as
            # "in progress" before invoking this generator. Without this
            # update the note would stay stuck at "in progress" even though
            # nothing ever executed.
            if original_task_note_path:
                task_id_for_status = task_context.get("task_id", "unknown_task")
                try:
                    self.update_task_status_in_obsidian(
                        original_task_note_path,
                        "routing_failed",
                        task_id_for_status,
                    )
                except Exception:
                    logger.error(
                        "Failed to mark routing_failed on Obsidian note.",
                        exc_info=True,
                    )
            # Generic message to the SSE client; sanitized detail is
            # already in server logs above (CodeQL py/stack-trace-exposure).
            yield {
                "type": "error",
                "error": "Routing failed; see server logs for details.",
            }
            return

        # From here on, mirror assign_and_execute_task's responsibilities
        # but interleave token emission while the agent is producing output.
        task_id = task_context.get("task_id", "auto_generated")
        agent = self.agent_registry.get_agent(agent_name)
        if not agent:
            yield {
                "type": "error",
                "error": f"Agent '{agent_name}' not registered with the orchestrator.",
            }
            return

        sandbox_result = self._check_dispatch(agent, task_context)
        if not sandbox_result.allowed:
            if original_task_note_path:
                self.update_task_status_in_obsidian(
                    original_task_note_path,
                    "failed",
                    task_id,
                )
            self._log_provenance_action(
                task_context,
                "dispatch_denied",
                "sandbox",
                {
                    "task_id": task_id,
                    "agent": agent_name,
                    "capability": task_context.get("required_capability"),
                    "violation_type": sandbox_result.violation_type,
                    "reason": sandbox_result.reason,
                },
            )
            yield {
                "type": "error",
                "error": "Task denied by governance policy; see server logs.",
            }
            return

        task_success = False
        results: Dict[str, Any] = {}
        task_start_time = time.perf_counter()
        self._log_provenance_action(
            task_context,
            "task_start",
            "orchestrator",
            {
                "task_id": task_id,
                "agent": agent_name,
                "capability": task_context.get("required_capability"),
                "routing_scope": task_context.get("routing_scope"),
            },
            f"Starting streaming task {task_id} with {agent_name}",
        )
        try:
            enriched_context = self._enrich_task_with_memory(task_context)

            stream_task = getattr(agent, "stream_task", None)
            if getattr(agent, "supports_streaming", False) and callable(stream_task):
                for event in stream_task(enriched_context):
                    etype = event.get("type")
                    if etype == "token":
                        yield {"type": "token", "text": event.get("text", "")}
                    elif etype == "final":
                        results = event.get("result") or {}
                        break
                if not results:
                    # Agent's stream_task didn't terminate with a final event;
                    # synthesise a failure result rather than silently
                    # dropping the run.
                    results = {
                        "status": "failed",
                        "summary": "Streaming agent did not emit a final event.",
                    }
            else:
                # Non-streaming agent: run synchronously, emit the whole
                # response as a single token event so the UI animation is
                # consistent.
                results = agent.perform_task(enriched_context)
                summary_text = str(results.get("summary", ""))
                if summary_text:
                    yield {"type": "token", "text": summary_text}

            task_success = results.get("status") != "failed"

            # Persist report (same path as assign_and_execute_task).
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
                    metadata={
                        "agent": agent_name,
                        "task_id": task_id,
                        "provenance_id": task_context.get("provenance_id"),
                        "routing_scope": task_context.get("routing_scope"),
                        "atp_action_type": task_context.get("atp_action_type"),
                    },
                )
                self._log_provenance_action(
                    task_context,
                    "memory_persisted",
                    "memory_bus",
                    {"task_id": task_id, "path": report_path},
                )
            except Exception:
                # exc_info=True attaches the stack trace; agent_name omitted
                # from the message to avoid user-controlled data flowing into
                # log records (CodeQL py/log-injection).
                logger.error("Failed to persist streaming report.", exc_info=True)

            if original_task_note_path:
                self.update_task_status_in_obsidian(
                    original_task_note_path,
                    "completed" if task_success else "failed",
                    task_id,
                )

        except Exception:  # noqa: BLE001
            # Same rationale as above -- exception detail is on exc_info,
            # not interpolated into the message. Generic strings flow to
            # the SSE client (CodeQL py/stack-trace-exposure); the full
            # exception is preserved in server logs via exc_info=True.
            logger.error("Streaming execution failed.", exc_info=True)
            task_success = False
            results = {
                "status": "failed",
                "error": "Task execution failed; see server logs for details.",
                "summary": "Task failed; see server logs for details.",
            }
            if original_task_note_path:
                self.update_task_status_in_obsidian(
                    original_task_note_path, "failed", task_id
                )

        # Full learning update fires regardless of branch after the stream has
        # reached a terminal result, matching the JSON executor's trail.
        hebbian_error: Optional[str] = None
        try:
            learning = self._update_hebbian_weights(
                agent_name,
                task_id,
                task_success,
                task_type=(
                    task_context.get("routing_scope")
                    or task_context.get("required_capability")
                ),
                results=results,
                duration_ms=(time.perf_counter() - task_start_time) * 1000,
            )
            self._log_provenance_action(
                task_context,
                "learning_updated",
                "hebbian_weights",
                {
                    "task_id": task_id,
                    "agent": agent_name,
                    "task_type": learning.get("task_type"),
                    "delta": learning.get("delta"),
                    "weight": learning.get("weight"),
                    "sentinel_alert": learning.get("sentinel_alert", False),
                },
            )
        except Exception:
            logger.error("Hebbian update failed in streaming executor.", exc_info=True)
            # Surface the failure to the client. The non-streaming
            # assign_and_execute_task path lets the exception propagate
            # and returns HTTP 500; in a streaming connection that would
            # truncate the SSE, so we keep the connection alive and
            # report the failure inline. The task itself still completed
            # -- only the learning update was lost.
            hebbian_error = "Hebbian persistence failed; see server logs."

        # Compose the error field: prefer the agent-level error if any,
        # otherwise the Hebbian-update error, otherwise None.
        complete_error = results.get("error") or hebbian_error

        self._log_provenance_action(
            task_context,
            "task_completed" if task_success else "task_failed",
            "orchestrator",
            {
                "task_id": task_id,
                "agent": agent_name,
                "status": "success" if task_success else "failed",
                "error": complete_error,
            },
            duration_ms=(time.perf_counter() - task_start_time) * 1000,
        )

        yield {
            "type": "complete",
            "task_id": task_id,
            "agent_name": agent_name,
            "status": "success" if task_success else "failed",
            "summary": results.get("summary", "Task executed"),
            "note_path": original_task_note_path,
            "error": complete_error,
            "provenance_id": task_context.get("provenance_id"),
            "atp": task_context.get("atp"),
        }

    def _update_hebbian_weights(
        self,
        agent_name: str,
        task_id: str,
        success: bool,
        task_type: Optional[str] = None,
        results: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
    ) -> dict:
        """
        Update Hebbian connection weights based on task outcome.

        Args:
            agent_name: Name of the agent that executed the task
            task_id: ID of the task
            success: Whether the task succeeded
            task_type: Capability/task type used for future scoped routing
            results: Structured agent result used to extract output quality
            duration_ms: End-to-end execution duration for timing memory
        """
        performance = self._outcome_performance(results or {}, success)
        learning = self.hebbian.record_outcome(
            agent_name,
            task_id,
            success=success,
            performance=performance,
            task_type=task_type,
            duration_ms=duration_ms,
        )
        registry_metrics = self.learning_governance.record_execution_outcome(
            agent_name,
            success=success,
            learning=learning,
        )
        trust_score = registry_metrics["trust_score"]

        logger.info(
            "Hebbian outcome %s -> %s (weight=%.4f, delta=%.4f, "
            "performance=%.3f, trust=%.3f)",
            _sanitize_for_log(agent_name),
            _sanitize_for_log(task_id),
            learning["weight"],
            learning["delta"],
            performance,
            trust_score,
        )
        if learning.get("sentinel_alert"):
            logger.warning(
                "Hebbian sentinel review signal for %s / %s "
                "(oscillation=%.3f, samples=%d)",
                _sanitize_for_log(agent_name),
                _sanitize_for_log(task_type),
                learning.get("oscillation_rate", 0.0),
                learning.get("sentinel_samples", 0),
            )
        return {**learning, **registry_metrics}

    def _check_dispatch(self, agent, task_context: Dict[str, Any]):
        """Run the production sandbox preflight for one agent dispatch."""
        capability = task_context.get("required_capability")
        declared = list(getattr(agent, "capabilities", []) or [])
        if (
            capability
            and capability not in declared
            and self.hebbian_router.fallback_capability in declared
        ):
            capability = self.hebbian_router.fallback_capability
        policy_loader = getattr(agent, "get_sandbox_policies", None)
        policies = policy_loader() if callable(policy_loader) else []
        if not isinstance(policies, list):
            policies = []
        sandbox = AgentSandbox(
            agent.name,
            policies=policies,
            registry=self.agent_registry,
            violation_recorder=self.learning_governance.record_violation,
            capabilities=declared,
        )
        dispatch_result = sandbox.check_dispatch(capability)
        if not dispatch_result.allowed:
            return dispatch_result

        action_loader = getattr(agent, "get_sandbox_actions", None)
        actions = action_loader(task_context) if callable(action_loader) else []
        if not isinstance(actions, list):
            actions = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            result = sandbox.check_action(
                str(action.get("tool_name", "")),
                path=action.get("path"),
                operation=action.get("operation"),
            )
            if not result.allowed:
                return result
        return dispatch_result

    def log_routing_decision(
        self,
        task_context: Dict[str, Any],
        agent_name: str,
        *,
        decision=None,
        source: str = "orchestrator",
        pinned: bool = False,
    ) -> None:
        """Persist the chosen route and full candidate breakdown."""
        self._log_provenance_action(
            task_context,
            "routing_decision",
            "hebbian_router" if decision is not None else "agent_registry",
            {
                "task_id": task_context.get("task_id"),
                "required_capability": task_context.get("required_capability"),
                "chosen_agent": agent_name,
                "pinned": pinned,
                "source": source,
                "decision": decision.to_dict() if decision is not None else None,
            },
            f"Routed task to {agent_name}",
        )

    @staticmethod
    def _outcome_performance(results: Dict[str, Any], success: bool) -> float:
        """Resolve a normalized target activation from an agent result."""
        if not success:
            return 0.0
        candidates = [
            results.get("performance_score"),
            results.get("quality_score"),
            results.get("confidence"),
            results.get("score"),
        ]
        nested_metrics = results.get("metrics")
        if isinstance(nested_metrics, dict):
            candidates.extend(
                [
                    nested_metrics.get("performance"),
                    nested_metrics.get("quality"),
                    nested_metrics.get("confidence"),
                ]
            )
        for value in candidates:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric = float(value)
                if 1.0 < numeric <= 100.0:
                    numeric /= 100.0
                return max(0.0, min(1.0, numeric))
        return 1.0

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
        self, relative_note_path: str, new_status: str, task_id: Optional[str] = None
    ):
        """Updates the status of a specific task note in Obsidian.

        Args:
            relative_note_path (str): Vault-relative note path to read or update.
            new_status (str): Status value to persist in the note or record.
            task_id (str): Identifier of the task being processed.

        Returns:
            None: This function does not return a value.
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
        """Create a new task note in the Obsidian input directory.

        Args:
            task_data (dict): Structured task payload to serialize into a note.
            filename (str | None): Optional filename override for the created note.

        Returns:
            str: Vault-relative path to the newly created task note.
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
        """Execute every pending task discovered in the Obsidian input directory.

        Returns:
            dict: Batch summary containing task counts and per-task execution results.
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
        """Display Hebbian network statistics.

        Returns:
            None: This function does not return a value.
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
        """Display Hebbian statistics for a specific agent.

        Args:
            agent_name (str): Name of the agent involved in the operation.

        Returns:
            None: This function does not return a value.
        """
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
