import argparse
import os
from datetime import datetime

from src.mcp.config import AGENT_INPUT_DIR, AGENT_OUTPUT_DIR, OBSIDIAN_VAULT_PATH
from src.mcp.orchestrator import Orchestrator
from src.utils.helpers import logger

def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MCP and optionally send a one-off instruction to an agent.")
    parser.add_argument(
        "-i",
        "--instruction",
        help="Instruction to send directly to an agent (e.g., 'Please write a note about ...')."
    )
    parser.add_argument(
        "-a",
        "--agent",
        default="research_agent",
        help="Agent key to handle the instruction (default: research_agent)."
    )
    parser.add_argument(
        "-t",
        "--title",
        help="Optional title to use for the instruction task/note."
    )
    parser.add_argument(
        "--skip-demos",
        action="store_true",
        help="Skip creating demo notes and the hard-coded summarizer example."
    )
    return parser.parse_args()

def setup_example_task_note(obs_manager):
    """
    Creates an example task note in the Obsidian Agent Inputs folder
    if one doesn't already exist, for demonstration purposes.
    """
    example_filename = "Example Research Task.md"
    relative_path = os.path.join(AGENT_INPUT_DIR, example_filename)
    full_path = obs_manager._get_full_path(relative_path) # Access internal for convenience

    if not full_path.is_file():
        logger.info(f"Creating example task note at {relative_path}")
        content = f"""---\ntask_id: {datetime.now().strftime('%Y%m%d%H%M%S')}\nagent: research_agent\nstatus: pending\ntags: ["example", "research"]\n---\n\n# Research Task: Artificial Intelligence Ethics\n\n## Context\n\nProvide an overview of the current ethical considerations surrounding the development and deployment of Artificial Intelligence. Focus on privacy, bias, and accountability.\n\nKeywords: AI ethics, privacy, bias, accountability, machine learning\nTarget: [[AI Concepts]]\nSource: Internet\n\n## Subtasks\n\n- [ ]  Research current debates on AI ethics\n- [ ]  Find examples of AI bias in real-world applications\n- [ ]  Summarize key regulations or frameworks proposed for AI accountability\n"""
        obs_manager.write_note(relative_path, content, overwrite=False)
        logger.info(f"Example task note '{example_filename}' created. Please review it in your Obsidian vault.")
    else:
        logger.info(f"Example task note '{example_filename}' already exists.")

def handle_user_instruction(orchestrator: Orchestrator, instruction: str, agent_name: str, title: str | None = None):
    """Create a task from a user instruction and dispatch it to the requested agent."""
    if not instruction.strip():
        logger.info("No instruction text provided. Skipping direct agent dispatch.")
        return

    if agent_name not in orchestrator.agents:
        logger.error(f"Agent '{agent_name}' is not registered. Available agents: {', '.join(orchestrator.agents.keys())}")
        return

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    task_id = f"user_instruction_{timestamp}"
    task_title = title or instruction.strip().split("\n")[0][:80] or "User Instruction"
    task_data = {
        "task_id": task_id,
        "title": task_title,
        "context": instruction,
        "content": instruction,
        "agent": agent_name,
        "status": "pending",
        "tags": ["user_instruction", agent_name]
    }

    logger.info(f"\n--- User Instruction: Dispatching to '{agent_name}' ---")
    try:
        note_path = orchestrator.create_new_task_in_obsidian(task_data)
        orchestrator.update_task_status_in_obsidian(note_path, 'in progress', task_id)
    except Exception as exc:
        logger.error(f"Failed to record instruction in Obsidian before execution: {exc}")
        note_path = None

    try:
        orchestrator.assign_and_execute_task(agent_name, task_data, note_path)
        logger.info(f"Instruction processed by '{agent_name}'.")
    except Exception as exc:
        logger.error(f"Error processing instruction with '{agent_name}': {exc}")
        if note_path:
            orchestrator.update_task_status_in_obsidian(note_path, 'failed', task_id)

def main():
    args = parse_cli_args()
    logger.info("Starting Multi-Agent Coordination Platform...")

    if not os.path.exists(OBSIDIAN_VAULT_PATH):
        logger.error(f"Error: Obsidian vault path '{OBSIDIAN_VAULT_PATH}' does not exist.")
        logger.error("Please update 'mcp_obsidian_system/.env' with your correct vault path.")
        return

    orchestrator = Orchestrator()

    # --- Optional: Set up demo content and sample direct task ---
    if not args.skip_demos and not args.instruction:
        setup_example_task_note(orchestrator.obs_manager)

        logger.info("\n--- MCP Operations ---")
        logger.info("\n--- Scenario 1: Direct Task Assignment (Summarizer Agent) ---")
        direct_task_context = {
            "task_id": "direct_summary_T001",
            "title": "Summarize provided text",
            "content": "Large Language Models (LLMs) are a class of artificial intelligence models that are trained on vast amounts of text data. They are capable of understanding and generating human-like text, performing tasks such as translation, summarization, question-answering, and content creation. Their development has rapidly advanced in recent years, leading to significant breakthroughs in natural language processing and various applications across industries.",
            "agent": "summarizer_agent",
            "status": "pending" # This status is for internal tracking, not written back here
        }

        try:
            orchestrator.assign_and_execute_task("summarizer_agent", direct_task_context)
            logger.info(f"Direct summary task completed. Report written to Obsidian: {AGENT_OUTPUT_DIR}/summarizer_agent_Report_direct_summary_T001_*.md")
        except ValueError as e:
            logger.error(f"Failed to assign direct task: {e}")
    else:
        logger.info("Skipping demo note creation and static summarizer task.")

    # --- User-provided instruction (CLI) ---
    if args.instruction:
        handle_user_instruction(orchestrator, args.instruction, args.agent, args.title)

    # --- Scenario 2: Check for tasks from Obsidian ---
    logger.info("\n--- Scenario 2: Checking for new tasks in Obsidian (Research Agent) ---")
    new_tasks = orchestrator.check_for_new_tasks_from_obsidian()

    if new_tasks:
        logger.info(f"Found {len(new_tasks)} new pending tasks in Obsidian.")
        for original_note_path, task_data in new_tasks:
            agent_name = task_data.get('agent')
            task_title = task_data.get('title', 'Untitled Task')

            if agent_name in orchestrator.agents:
                logger.info(f"Processing task '{task_title}' for agent '{agent_name}' from '{original_note_path}'")

                # First, update task status to 'in progress' in Obsidian
                orchestrator.update_task_status_in_obsidian(original_note_path, 'in progress', task_data['task_id'])

                # Execute the task
                try:
                    orchestrator.assign_and_execute_task(agent_name, task_data, original_note_path)
                    logger.info(f"Task '{task_title}' completed by {agent_name}.")
                except Exception as e:
                    logger.error(f"Error processing task '{task_title}' for {agent_name}: {e}")
                    orchestrator.update_task_status_in_obsidian(original_note_path, 'failed', task_data['task_id'])
            else:
                logger.warning(f"No agent found for task '{task_title}' (agent: {agent_name}). Skipping.")
                orchestrator.update_task_status_in_obsidian(original_note_path, 'agent_not_found', task_data['task_id'])
    else:
        logger.info("No new pending tasks found in Obsidian input folder.")
        logger.info(f"Remember to create a new Markdown note in '{OBSIDIAN_VAULT_PATH}/{AGENT_INPUT_DIR}' with 'status: pending' in its YAML frontmatter, for example:")
        logger.info("""---\ntask_id: T_NEW_RESEARCH\nagent: research_agent\nstatus: pending\n---\n\n# New Topic for Research\n\nTopic: The future of renewable energy technologies\nContext: Research emerging trends and key players.\nKeywords: solar, wind, geothermal, fusion\n""")

if __name__ == "__main__":
    main()
