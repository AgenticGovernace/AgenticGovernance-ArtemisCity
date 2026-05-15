import argparse
import os
from datetime import datetime
from typing import Any, Optional
import src.mcp.config
from src.mcp.orchestrator import Orchestrator
from src.utils.helpers import logger
from src.utils.run_logger import init_run_logger

AGENT_NAME_MAP = {
    "artemis_agent": "Artemis Agent",
    "research_agent": "Research Agent",
    "summarizer_agent": "Summarizer Agent",
}


class TaskStatus:
    PENDING = "pending"
    IN_PROGRESS = "in progress"
    FAILED = "failed"
    NO_CAPABILITY = "no_capability"


DEFAULT_CAPABILITY = "web_search"


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MCP and optionally send a one-off instruction to an agent.",
        allow_abbrev=True,
    )
    parser.add_argument(
        "-i",
        "--instruction",
        help="Instruction to send directly to an agent (e.g., 'Please write a note about ...').",
    )
    parser.add_argument(
        "-c",
        "--capability",
        default=DEFAULT_CAPABILITY,
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


def setup_example_task_note(obs_manager: Any, memory_bus: Optional[Any] = None) -> None:
    """Create a demo task note in the Obsidian Agent Inputs folder if missing."""
    example_filename = "Example Research Task.md"
    relative_path = os.path.join(
        src.mcp.config.AGENT_INPUT_DIR,
        src.mcp.config.AGENT_OUTPUT_DIR,
        example_filename,
    )
    full_path = obs_manager._get_full_path(relative_path)

    if full_path.is_file():
        logger.info(f"Example task note '{example_filename}' already exists.")
        return

    logger.info(f"Creating example task note at {relative_path}")
    content = f"""---\ntask_id: {datetime.now().strftime('%Y%m%d%H%M%S')}\nrequired_capability: {DEFAULT_CAPABILITY}\nstatus: {TaskStatus.PENDING}\ntags: ["example", "research"]\n---\n\n# Research Task: Artificial Intelligence Ethics\n\n## Context\n\nProvide an overview of the current ethical considerations surrounding the development and deployment of Artificial Intelligence. Focus on privacy, bias, and accountability.\n\nKeywords: AI ethics, privacy, bias, accountability, machine learning\nTarget: [[AI Concepts]]\nSource: Internet\n\n## Subtasks\n\n- [ ]  Research current debates on AI ethics\n- [ ]  Find examples of AI bias in real-world applications\n- [ ]  Summarize key regulations or frameworks proposed for AI accountability\n"""
    if memory_bus:
        try:
            memory_bus.write_note_with_embedding(
                relative_path, content, metadata={"demo": True}, embed=True
            )
        except Exception as exc:
            logger.error(f"Failed to write example note via memory bus: {exc}")
            obs_manager.write_note(relative_path, content, overwrite=False)
    else:
        obs_manager.write_note(relative_path, content, overwrite=False)
    logger.info(
        f"Example task note '{example_filename}' created. Please review it in your Obsidian vault."
    )


def handle_user_instruction(
    orchestrator: Orchestrator,
    instruction: str,
    capability: str | None,
    title: str | None = None,
    agent_name: str | None = None,
) -> None:
    """Create a task from a user instruction and dispatch it based on capability or explicit agent selection."""
    if not instruction.strip():
        logger.info("No instruction text provided. Skipping direct agent dispatch.")
        return

    if agent_name in AGENT_NAME_MAP:
        agent_name = AGENT_NAME_MAP[agent_name]

    agent_for_dispatch = None
    effective_capability = capability
    if agent_name:
        agent_for_dispatch = orchestrator.agent_registry.get_agent(agent_name)
        if not agent_for_dispatch:
            logger.error(
                f"Agent '{agent_name}' not registered. Available: {orchestrator.agent_registry.get_agent_names()}"
            )
            return
        if not effective_capability:
            effective_capability = (
                agent_for_dispatch.capabilities[0]
                if agent_for_dispatch.capabilities
                else None
            )
    effective_capability = effective_capability or DEFAULT_CAPABILITY

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    task_id = f"user_instruction_{timestamp}"
    task_title = title or instruction.strip().split("\n")[0][:80] or "User Instruction"
    task_data: dict[str, Any] = {
        "task_id": task_id,
        "title": task_title,
        "context": instruction,
        "content": instruction,
        "required_capability": effective_capability,
        "status": TaskStatus.PENDING,
        "tags": ["user_instruction", effective_capability],
    }
    if agent_for_dispatch:
        task_data["agent"] = agent_name

    logger.info(
        f"\n--- User Instruction: Dispatching task with capability '{effective_capability}' ---"
    )
    try:
        note_path = orchestrator.create_new_task_in_obsidian(task_data)
        orchestrator.update_task_status_in_obsidian(note_path, TaskStatus.IN_PROGRESS, task_id)
    except Exception as exc:
        logger.error(f"Failed to record instruction in Obsidian before execution: {exc}")
        note_path = None

    try:
        if agent_for_dispatch:
            orchestrator.assign_and_execute_task(
                agent_for_dispatch.name, task_data, note_path
            )
            logger.info(f"Instruction processed by agent '{agent_for_dispatch.name}'.")
        else:
            orchestrator.route_and_execute_task(task_data, note_path)
            logger.info(
                f"Instruction processed for capability '{effective_capability}'."
            )
    except Exception as exc:
        logger.error(f"Error processing instruction: {exc}")
        if note_path:
            orchestrator.update_task_status_in_obsidian(note_path, TaskStatus.FAILED, task_id)


def main() -> None:
    args = parse_cli_args()

    run_logger = init_run_logger(log_dir="logs", db_path="data/run_logs.db")

    logger.info("Starting Multi-Agent Coordination Platform...")
    run_logger.log_event(
        "mcp_init", "main", {"args": vars(args)}, "MCP initialization started"
    )

    if not os.path.exists(src.mcp.config.OBSIDIAN_VAULT_PATH or ""):
        logger.error(
            f"Error: Obsidian vault path '{src.mcp.config.OBSIDIAN_VAULT_PATH}' does not exist."
        )
        logger.error(
            "Set OBSIDIAN_VAULT_PATH in the project '.env' or export it in your shell to point to your vault."
        )
        run_logger.log_event(
            "mcp_error",
            "main",
            {"error": "vault_not_found"},
            f"Vault path not found: {src.mcp.config.OBSIDIAN_VAULT_PATH}",
        )
        run_logger.finalize_run(status="error", summary={"error": "vault_not_found"})
        return

    orchestrator = Orchestrator()
    run_logger.log_event(
        "orchestrator_ready",
        "main",
        {
            "agents": orchestrator.agent_registry.get_agent_names()
            if orchestrator.agent_registry
            else []
        },
        "Orchestrator initialized",
    )

    if args.show_hebbian:
        orchestrator.show_hebbian_network_summary()
        return

    if args.agent_stats:
        agent_name = AGENT_NAME_MAP.get(args.agent_stats, args.agent_stats)
        orchestrator.show_agent_hebbian_stats(agent_name)
        return

    if not args.skip_demos:
        setup_example_task_note(orchestrator.obs_manager, orchestrator.memory_bus)

        logger.info("\n--- Scenario 1: Direct Task Assignment (Summarizer Agent) ---")
        direct_task_context = {
            "task_id": "direct_summary_T001",
            "title": "Summarize provided text",
            "content": (
                "Large Language Models (LLMs) are a class of artificial intelligence models that "
                "are trained on vast amounts of text data. They are capable of understanding and "
                "generating human-like text, performing tasks such as translation, summarization, "
                "question-answering, and content creation. Their development has rapidly advanced "
                "in recent years, leading to significant breakthroughs in natural language processing "
                "and various applications across industries."
            ),
            "required_capability": "text_summarization",
            "status": TaskStatus.PENDING,
            "tags": ["demo", "summarization"],
            "agent": "Summarizer Agent",
            "metadata": {"source": "direct_demo", "demo": True},
            "log": [
                {
                    "timestamp": datetime.now().isoformat(),
                    "event": "Task created for direct instruction demo.",
                }
            ],
        }

        try:
            orchestrator.route_and_execute_task(direct_task_context)
            logger.info("Direct summary task completed. Report written to Obsidian.")
        except ValueError as ve:
            logger.error(f"Value error during direct task assignment: {ve}")
        except Exception as e:
            logger.error(f"Failed to assign direct task: {e}")
    else:
        logger.info("Skipping demo note creation and static summarizer task.")

    if args.instruction:
        handle_user_instruction(
            orchestrator, args.instruction, args.capability, args.title, args.agent
        )

    logger.info("\n--- Scenario 2: Checking for new tasks in Obsidian ---")
    new_tasks = orchestrator.check_for_new_tasks_from_obsidian() or []

    if new_tasks:
        logger.info(f"Found {len(new_tasks)} new pending tasks in Obsidian.")
        for original_note_path, task_data in new_tasks:
            task_title = task_data.get("title", "Untitled Task")
            capability = task_data.get("required_capability")
            if not capability:
                logger.warning(
                    f"Task '{task_title}' has no 'required_capability'. Skipping."
                )
                orchestrator.update_task_status_in_obsidian(
                    original_note_path, TaskStatus.NO_CAPABILITY, task_data["task_id"]
                )
                continue
            logger.info(
                f"Processing task '{task_title}' with capability '{capability}' from '{original_note_path}'"
            )
            orchestrator.update_task_status_in_obsidian(
                original_note_path, TaskStatus.IN_PROGRESS, task_data["task_id"]
            )
            try:
                orchestrator.route_and_execute_task(task_data, original_note_path)
                logger.info(f"Task '{task_title}' completed.")
            except Exception as e:
                logger.error(f"Error processing task '{task_title}': {e}")
                orchestrator.update_task_status_in_obsidian(
                    original_note_path, TaskStatus.FAILED, task_data["task_id"]
                )
    else:
        logger.info("No new pending tasks found in Obsidian input folder.")
        logger.info(
            "Remember to create a new Markdown note in '%s/%s' "
            "with 'status: pending' and 'required_capability' in its YAML frontmatter, "
            "for example:",
            src.mcp.config.OBSIDIAN_VAULT_PATH,
            src.mcp.config.AGENT_INPUT_DIR,
        )
        logger.info(
            f"---\ntask_id: T_NEW_RESEARCH\nrequired_capability: {DEFAULT_CAPABILITY}\nstatus: {TaskStatus.PENDING}\n---\n\n# New Topic for Research\n\nTopic: The future of renewable energy technologies\nContext: Research emerging trends and key players.\nKeywords: solar, wind, geothermal, fusion\n"
        )

    run_logger.finalize_run(
        status="completed",
        summary={
            "tasks_found": len(new_tasks),
            "tasks_failed": sum(1 for _, t in new_tasks if t.get("status") == TaskStatus.FAILED),
            "tasks_no_capability": sum(
                1 for _, t in new_tasks if t.get("status") == TaskStatus.NO_CAPABILITY
            ),
            "skip_demos": args.skip_demos,
            "instruction": args.instruction,
            "capability": args.capability,
            "agent": args.agent,
            "title": args.title,
            "show_hebbian": args.show_hebbian,
            "agent_stats": args.agent_stats,
        },
    )
    logger.info(f"Run log saved to: {run_logger.md_path}")


if __name__ == "__main__":
    main()
