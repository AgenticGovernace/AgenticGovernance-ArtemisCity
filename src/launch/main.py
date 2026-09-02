#!/usr/bin/env python3
"""Canonical CLI entry point for orchestrator tasks and demonstrations."""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path so "src.*" imports resolve
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import src.mcp.orchestrator
from src.mcp.config import AGENT_INPUT_DIR, OBSIDIAN_VAULT_PATH
from src.utils.helpers import logger, sanitize_for_log
from src.utils.run_logger import init_run_logger


def _sql_memory_selected() -> bool:
    """Return whether runtime configuration requires canonical SQL storage."""
    backend = os.getenv("ARTEMIS_MEMORY_BACKEND", "legacy").strip().lower()
    return backend not in {"", "legacy", "disabled"}


def parse_cli_args() -> argparse.Namespace:
    """Parse command-line arguments for the CLI entry point.

    Returns:
        argparse.Namespace: Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Run MCP and optionally send a one-off instruction to an agent.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "-i",
        "--instruction",
        help="Instruction to send directly to an agent (e.g., 'Please write a note about ...').",
    )
    parser.add_argument(
        "-c",
        "--capability",
        default=None,
        help="Required capability to handle the instruction. If omitted and --agent is set, the agent's primary capability is used; otherwise defaults to web_search.",
    )
    parser.add_argument(
        "--agent",
        help="Explicit agent to run; capability is derived from the registry if not provided.",
    )
    parser.add_argument(
        "-t", "--title", help="Optional title to use for the instruction task/note."
    )
    parser.add_argument(
        "--skip-demos",
        action="store_true",
        help="Skip creating demo notes and the hard-coded summarizer example.",
    )
    parser.add_argument(
        "--show-hebbian",
        action="store_true",
        help="Show Hebbian learning network summary and exit.",
    )
    parser.add_argument(
        "--agent-stats", help="Show Hebbian statistics for a specific agent and exit."
    )
    return parser.parse_args()


def setup_example_task_note(obs_manager, memory_bus=None):
    """Creates an example task note in the Obsidian Agent Inputs folder
    if one doesn't already exist, for demonstration purposes.

    Args:
        obs_manager: Obsidian manager instance used for vault access.
        memory_bus: Memory bus instance used for note persistence.

    Returns:
        None: This function does not return a value.
    """
    example_filename = "Example Research Task.md"
    relative_path = os.path.join(AGENT_INPUT_DIR, example_filename)
    sql_mode = (
        memory_bus is not None and getattr(memory_bus, "sql_store", None) is not None
    )
    if sql_mode:
        note_exists = memory_bus.read_exact(relative_path) is not None
    else:
        full_path = obs_manager._get_full_path(
            relative_path
        )  # Access internal for legacy compatibility
        note_exists = full_path.is_file()

    if not note_exists:
        logger.info("Creating example task note at %s", sanitize_for_log(relative_path))
        content = f"""---\ntask_id: {datetime.now().strftime("%Y%m%d%H%M%S")}\nrequired_capability: web_search\nstatus: pending\ntags: ["example", "research"]\n---\n\n# Research Task: Artificial Intelligence Ethics\n\n## Context\n\nProvide an overview of the current ethical considerations surrounding the development and deployment of Artificial Intelligence. Focus on privacy, bias, and accountability.\n\nKeywords: AI ethics, privacy, bias, accountability, machine learning\nTarget: [[AI Concepts]]\nSource: Internet\n\n## Subtasks\n\n- [ ]  Research current debates on AI ethics\n- [ ]  Find examples of AI bias in real-world applications\n- [ ]  Summarize key regulations or frameworks proposed for AI accountability\n"""
        if memory_bus:
            try:
                memory_bus.write_note_with_embedding(
                    relative_path, content, metadata={"demo": True}, embed=True
                )
            except Exception as exc:
                logger.error(
                    "Failed to write example note via memory bus: %s",
                    sanitize_for_log(exc),
                )
                if sql_mode:
                    raise
                obs_manager.write_note(relative_path, content, overwrite=False)
        else:
            obs_manager.write_note(relative_path, content, overwrite=False)
        logger.info(
            "Example task note '%s' created. Please review it in your Obsidian vault.",
            sanitize_for_log(example_filename),
        )
    else:
        logger.info(
            "Example task note '%s' already exists.", sanitize_for_log(example_filename)
        )


def handle_user_instruction(
    orchestrator: src.mcp.orchestrator.Orchestrator,
    instruction: str,
    capability: str | None,
    title: str | None = None,
    agent_name: str | None = None,
):
    """Create a task from a user instruction and dispatch it based on capability or explicit agent selection.

    Args:
        orchestrator (Orchestrator): Orchestrator instance used to route and execute tasks.
        instruction (str): Instruction text supplied by the caller.
        capability (str | None): Capability name used to route or classify work.
        title (str | None): Human-readable title for the task, note, or report.
        agent_name (str | None): Name of the agent involved in the operation.

    Returns:
        None: This function does not return a value.
    """
    if not instruction.strip():
        logger.info("No instruction text provided. Skipping direct agent dispatch.")
        return

    # Agent name mapping for convenience
    agent_name_map = {
        "artemis_agent": "Artemis Agent",
        "research_agent": "Research Agent",
        "summarizer_agent": "Summarizer Agent",
        "llm_agent": "LLM Agent",
    }
    if agent_name in agent_name_map:
        agent_name = agent_name_map[agent_name]

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    task_id = f"user_instruction_{timestamp}"
    task_title = title or instruction.strip().split("\n")[0][:80] or "User Instruction"
    agent_for_dispatch = None
    effective_capability = capability
    if agent_name:
        agent_for_dispatch = orchestrator.agent_registry.get_agent(agent_name)
        if not agent_for_dispatch:
            logger.error(
                "Agent '%s' not registered. Available: %s",
                sanitize_for_log(agent_name),
                sanitize_for_log(orchestrator.agent_registry.get_agent_names()),
            )
            return
        derived_capability = (
            agent_for_dispatch.capabilities[0]
            if agent_for_dispatch.capabilities
            else None
        )
        if not effective_capability:
            if not derived_capability:
                logger.error(
                    "Agent '%s' has no capabilities defined; cannot dispatch.",
                    sanitize_for_log(agent_name),
                )
                return
            effective_capability = derived_capability
    if not effective_capability:
        # Generic instructions default to the general-purpose LLM capability.
        effective_capability = "llm_chat"

    task_data = {
        "task_id": task_id,
        "title": task_title,
        "context": instruction,
        "content": instruction,
        "required_capability": effective_capability,
        "status": "pending",
        "tags": ["user_instruction", effective_capability],
    }

    if agent_for_dispatch:
        task_data["agent"] = agent_for_dispatch.name

    logger.info(
        "\n--- User Instruction: Dispatching task with capability '%s' ---",
        sanitize_for_log(effective_capability),
    )
    try:
        note_path = orchestrator.create_new_task_in_obsidian(task_data)
        orchestrator.update_task_status_in_obsidian(note_path, "in progress", task_id)
    except Exception as exc:
        logger.error(
            "Failed to record instruction in Obsidian before execution: %s",
            sanitize_for_log(exc),
        )
        note_path = None

    try:
        if agent_for_dispatch:
            orchestrator.assign_and_execute_task(
                agent_for_dispatch.name, task_data, note_path
            )
            logger.info(
                "Instruction processed by agent '%s'.",
                sanitize_for_log(agent_for_dispatch.name),
            )
        else:
            orchestrator.route_and_execute_task(task_data, note_path)
            logger.info(
                "Instruction processed for capability '%s'.",
                sanitize_for_log(effective_capability),
            )
    except Exception as exc:
        logger.error("Error processing instruction: %s", sanitize_for_log(exc))
        if note_path:
            orchestrator.update_task_status_in_obsidian(note_path, "failed", task_id)


def main():
    """Run the primary workflow exposed by this module.

    Returns:
        None: This function does not return a value.
    """
    args = parse_cli_args()

    # Initialize run logger for comprehensive tracking
    run_logger = init_run_logger()

    logger.info("Starting Multi-Agent Coordination Platform...")
    run_logger.log_event(
        "mcp_init", "main", {"args": vars(args)}, "MCP initialization started"
    )

    if not _sql_memory_selected() and not os.path.exists(OBSIDIAN_VAULT_PATH):
        logger.error(
            "Error: Obsidian vault path '%s' does not exist.",
            sanitize_for_log(OBSIDIAN_VAULT_PATH),
        )
        logger.error(
            "Set OBSIDIAN_VAULT_PATH in the project '.env' or export it in your shell to point to your vault."
        )
        run_logger.log_event(
            "mcp_error",
            "main",
            {"error": "vault_not_found"},
            f"Vault path not found: {OBSIDIAN_VAULT_PATH}",
        )
        run_logger.finalize_run(status="error", summary={"error": "vault_not_found"})
        return

    orchestrator = src.mcp.orchestrator.Orchestrator()
    run_logger.log_event(
        "orchestrator_ready",
        "main",
        {"agents": orchestrator.agent_registry.get_agent_names()},
        "Orchestrator initialized",
    )

    # Agent name mapping for convenience
    agent_name_map = {
        "artemis_agent": "Artemis Agent",
        "research_agent": "Research Agent",
        "summarizer_agent": "Summarizer Agent",
        "llm_agent": "LLM Agent",
    }

    # Handle Hebbian statistics display
    if args.show_hebbian:
        orchestrator.show_hebbian_network_summary()
        return

    if args.agent_stats:
        agent_name = agent_name_map.get(args.agent_stats, args.agent_stats)
        orchestrator.show_agent_hebbian_stats(agent_name)
        return

    # --- Optional: Set up demo content and sample direct task ---
    if not args.skip_demos:
        setup_example_task_note(orchestrator.obs_manager, orchestrator.memory_bus)

        logger.info("\n--- MCP Operations ---")
        logger.info("\n--- Scenario 1: Direct Task Assignment (Summarizer Agent) ---")
        direct_task_context = {
            "task_id": "direct_summary_T001",
            "title": "Summarize provided text",
            "content": "Large Language Models (LLMs) are a class of artificial intelligence models that are trained on vast amounts of text data. They are capable of understanding and generating human-like text, performing tasks such as translation, summarization, question-answering, and content creation. Their development has rapidly advanced in recent years, leading to significant breakthroughs in natural language processing and various applications across industries.",
            "required_capability": "text_summarization",
            "status": "pending",
        }

        try:
            orchestrator.route_and_execute_task(direct_task_context)
            logger.info("Direct summary task completed. Report written to Obsidian.")
        except ValueError as e:
            logger.error("Failed to assign direct task: %s", sanitize_for_log(e))
    else:
        logger.info("Skipping demo note creation and static summarizer task.")

    # --- User-provided instruction (CLI) ---
    if args.instruction:
        handle_user_instruction(
            orchestrator, args.instruction, args.capability, args.title, args.agent
        )

    # --- Scenario 2: Check for tasks from Obsidian ---
    logger.info("\n--- Scenario 2: Checking for new tasks in Obsidian ---")
    new_tasks = orchestrator.check_for_new_tasks_from_obsidian()

    if new_tasks:
        logger.info("Found %s new pending tasks in Obsidian.", len(new_tasks))
        for original_note_path, task_data in new_tasks:
            task_title = task_data.get("title", "Untitled Task")
            capability = task_data.get("required_capability")

            if capability:
                logger.info(
                    "Processing task '%s' with capability '%s' from '%s'",
                    sanitize_for_log(task_title),
                    sanitize_for_log(capability),
                    sanitize_for_log(original_note_path),
                )

                # First, update task status to 'in progress' in Obsidian
                orchestrator.update_task_status_in_obsidian(
                    original_note_path, "in progress", task_data["task_id"]
                )

                # Execute the task
                try:
                    orchestrator.route_and_execute_task(task_data, original_note_path)
                    logger.info("Task '%s' completed.", sanitize_for_log(task_title))
                except Exception as e:
                    logger.error(
                        "Error processing task '%s': %s",
                        sanitize_for_log(task_title),
                        sanitize_for_log(e),
                    )
                    orchestrator.update_task_status_in_obsidian(
                        original_note_path, "failed", task_data["task_id"]
                    )
            else:
                logger.warning(
                    "Task '%s' has no 'required_capability'. Skipping.",
                    sanitize_for_log(task_title),
                )
                orchestrator.update_task_status_in_obsidian(
                    original_note_path, "no_capability", task_data["task_id"]
                )
    else:
        logger.info("No new pending tasks found in Obsidian input folder.")
        logger.info(
            "Remember to create a new Markdown note in '%s/%s' with 'status: pending' and 'required_capability' in its YAML frontmatter, for example:",
            sanitize_for_log(OBSIDIAN_VAULT_PATH),
            sanitize_for_log(AGENT_INPUT_DIR),
        )
        logger.info(
            """---\ntask_id: T_NEW_RESEARCH\nrequired_capability: web_search\nstatus: pending\n---\n\n# New Topic for Research\n\nTopic: The future of renewable energy technologies\nContext: Research emerging trends and key players.\nKeywords: solar, wind, geothermal, fusion\n"""
        )

    # Finalize run logging with summary
    run_logger.finalize_run(
        status="completed",
        summary={
            "tasks_found": len(new_tasks) if new_tasks else 0,
            "skip_demos": args.skip_demos,
            "instruction_provided": bool(args.instruction),
        },
    )
    logger.info("Run log saved to: %s", sanitize_for_log(run_logger.md_path))


if __name__ == "__main__":
    main()
