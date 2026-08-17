"""Routing Kernel ATP Command-Line Interface.

Provides a unified, governed CLI entry point for executing natural language
and ATP-formatted instructions through the Artemis City Orchestrator,
Routing Kernel, Agent Registry, and Memory Bus.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is on sys.path
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import src.mcp.orchestrator
from src.agents.atp.atp_parser import ATPParser
from src.mcp.config import AGENT_INPUT_DIR, OBSIDIAN_VAULT_PATH
from src.utils.helpers import logger, sanitize_for_log
from src.utils.run_logger import init_run_logger


def _sql_memory_selected() -> bool:
    """Return whether runtime configuration requires canonical SQL storage."""
    backend = os.getenv("ARTEMIS_MEMORY_BACKEND", "legacy").strip().lower()
    return backend not in {"", "legacy", "disabled"}


def parse_atp_cli_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments for the ATP CLI.

    Args:
        args: Optional list of argument strings. If None, uses sys.argv[1:].

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Artemis City ATP CLI — Governed Routing Kernel & Agent Dispatch",
        allow_abbrev=False,
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Command or ATP instruction to execute (single-shot mode).",
    )
    parser.add_argument(
        "-i",
        "--instruction",
        default=None,
        help="Instruction text to execute through the routing kernel.",
    )
    parser.add_argument(
        "-f",
        "--file",
        default=None,
        help="Path to file containing prompt/ATP instruction to execute.",
    )
    parser.add_argument(
        "-c",
        "--capability",
        default=None,
        help="Required capability for routing (e.g. llm_chat, text_summarization, web_search, reasoning).",
    )
    parser.add_argument(
        "-a",
        "--agent",
        default=None,
        help="Pin execution to an explicit registered agent.",
    )
    parser.add_argument(
        "-t",
        "--title",
        default=None,
        help="Human-readable title for the task/report.",
    )
    parser.add_argument(
        "-z",
        "--target-zone",
        default=None,
        help="Target project/folder zone (e.g. /src/agents/).",
    )
    parser.add_argument(
        "-m",
        "--mode",
        default=None,
        help="ATP mode (Build, Review, Organize, Capture, Synthesize, Commit, Execute).",
    )
    parser.add_argument(
        "-p",
        "--priority",
        default=None,
        help="ATP priority (Critical, High, Normal, Low).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enforce strict ATP header validation.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output execution outcome as formatted JSON.",
    )
    parser.add_argument(
        "--show-routing",
        action="store_true",
        help="Show detailed candidate routing scores and selected path.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Force interactive ATP REPL mode.",
    )

    return parser.parse_args(args)


def build_task_payload(
    raw_text: str,
    *,
    capability: Optional[str] = None,
    agent_name: Optional[str] = None,
    title: Optional[str] = None,
    target_zone: Optional[str] = None,
    mode: Optional[str] = None,
    priority: Optional[str] = None,
    strict: bool = False,
) -> Dict[str, Any]:
    """Build a structured task context dictionary from CLI inputs.

    Args:
        raw_text: The user instruction or raw ATP block.
        capability: Optional required capability.
        agent_name: Optional explicit agent.
        title: Optional task title.
        target_zone: Optional target zone.
        mode: Optional ATP mode.
        priority: Optional ATP priority.
        strict: Whether strict ATP parsing is enforced.

    Returns:
        Dict[str, Any]: Task data context.
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    task_id = f"atp_cli_{timestamp}"
    task_title = title or raw_text.strip().split("\n")[0][:80] or "ATP Instruction"

    task_data: Dict[str, Any] = {
        "task_id": task_id,
        "title": task_title,
        "context": raw_text,
        "content": raw_text,
        "atp_raw": raw_text,
        "atp_strict": strict,
        "status": "pending",
        "tags": ["atp_cli"],
    }

    if capability:
        task_data["required_capability"] = capability
        task_data["_capability_explicit"] = True
    if agent_name:
        task_data["agent"] = agent_name
    if target_zone:
        task_data["target_zone"] = target_zone
    if mode:
        task_data["mode"] = mode
    if priority:
        task_data["priority"] = priority

    return task_data


def execute_instruction(
    orchestrator: src.mcp.orchestrator.Orchestrator,
    task_data: Dict[str, Any],
    *,
    show_routing: bool = False,
    as_json: bool = False,
) -> Dict[str, Any]:
    """Execute a task context through the Orchestrator and Routing Kernel.

    Args:
        orchestrator: Live Orchestrator instance.
        task_data: Task context dictionary.
        show_routing: Whether to print routing diagnostics.
        as_json: Whether to print structured JSON output.

    Returns:
        Dict[str, Any]: The execution outcome dictionary.
    """
    task_id = task_data.get("task_id", "unknown_task")

    # 1. Prepare ATP & context
    prepared_task = orchestrator.prepare_task_context(task_data)
    if not prepared_task.get("required_capability"):
        prepared_task["required_capability"] = "llm_chat"
    prepared_task.setdefault("routing_scope", prepared_task["required_capability"])

    # 2. Ensure Provenance
    prepared_task = orchestrator.ensure_task_provenance(prepared_task, source="atp_cli")

    # 3. Create task note in Obsidian if storage available
    note_path = None
    try:
        note_path = orchestrator.create_new_task_in_obsidian(prepared_task)
        orchestrator.update_task_status_in_obsidian(note_path, "in progress", task_id)
    except Exception as exc:
        logger.warning(
            "Obsidian note creation skipped or unavailable: %s",
            sanitize_for_log(exc),
        )

    # 4. Route and execute
    pinned_agent = prepared_task.get("agent")
    result: Dict[str, Any] = {}
    routing_path = "pinned" if pinned_agent else "kernel"
    selected_agent = pinned_agent

    try:
        if pinned_agent:
            agent_obj = orchestrator.agent_registry.get_agent(pinned_agent)
            if not agent_obj:
                raise ValueError(
                    f"Pinned agent '{pinned_agent}' is not registered. Available: "
                    f"{orchestrator.agent_registry.get_agent_names()}"
                )
            result = orchestrator.assign_and_execute_task(
                agent_obj.name, prepared_task, note_path
            )
            selected_agent = agent_obj.name
        else:
            result = orchestrator.route_and_execute_task(prepared_task, note_path)
            selected_agent = result.get("agent") or prepared_task.get("agent")
            routing_path = result.get("routing_path", "kernel")

        status = result.get("status", "success")
        summary = result.get("summary", "Task executed.")

        if as_json:
            output_payload = {
                "status": status,
                "task_id": task_id,
                "agent": selected_agent,
                "routing_path": routing_path,
                "provenance_id": prepared_task.get("provenance_id"),
                "summary": summary,
                "result": result,
            }
            print(json.dumps(output_payload, indent=2, default=str))
        else:
            print("\n" + "=" * 60)
            print(f"🏛️  ARTEMIS CITY — AGENT RESPONSE ({status.upper()})")
            print("=" * 60)
            print(f"Agent:        {selected_agent}")
            print(f"Routing Path: {routing_path}")
            print(f"Capability:   {prepared_task.get('required_capability')}")
            if prepared_task.get("provenance_id"):
                print(f"Provenance:   {prepared_task.get('provenance_id')}")
            print("-" * 60)
            print(summary)
            print("=" * 60 + "\n")

        return result

    except Exception as exc:
        logger.error("ATP execution error: %s", sanitize_for_log(exc))
        if note_path:
            try:
                orchestrator.update_task_status_in_obsidian(
                    note_path, "failed", task_id
                )
            except Exception:
                pass

        error_summary = f"Execution failed: {exc}"
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "task_id": task_id,
                        "error": str(exc),
                        "routing_path": routing_path,
                    },
                    indent=2,
                )
            )
        else:
            print(f"\n❌ Error: {exc}\n")

        return {"status": "failed", "error": str(exc), "summary": error_summary}


def run_interactive_atp_loop(
    orchestrator: src.mcp.orchestrator.Orchestrator,
    *,
    strict: bool = False,
    show_routing: bool = False,
) -> None:
    """Run the interactive Artemis City ATP REPL.

    Args:
        orchestrator: Live Orchestrator instance.
        strict: Whether to require strict ATP syntax.
        show_routing: Whether to print routing diagnostics.
    """
    print("\n" + "=" * 60)
    print("🏛️  Artemis City — Interactive ATP Kernel CLI (v1.0)")
    print("=" * 60)
    print("Type your instruction or paste ATP formatted blocks.")
    print("Commands:")
    print("  /agents   - List registered specialist agents")
    print("  /hebbian  - Show Hebbian learning weights")
    print("  /status   - Show memory and orchestrator status")
    print("  /help     - Show guidance on ATP format tags")
    print("  exit/quit - Exit interactive session")
    print("=" * 60 + "\n")

    parser = ATPParser()

    while True:
        try:
            line = input("artemis-atp> ").strip()
            if not line:
                continue
            if line.lower() in ["exit", "quit", ":q"]:
                print("Session closed. Farewell.")
                break

            if line == "/agents":
                agents = orchestrator.agent_registry.get_agent_names()
                print(f"Registered Agents: {', '.join(agents)}")
                continue

            if line == "/hebbian":
                orchestrator.show_hebbian_network_summary()
                continue

            if line == "/status":
                print(f"Vault Path:     {OBSIDIAN_VAULT_PATH}")
                print(
                    f"Memory Mode:    {'SQL/Authoritative' if _sql_memory_selected() else 'Obsidian/Legacy'}"
                )
                print(
                    f"Routing Kernel: {'Enabled' if orchestrator.routing_kernel else 'Legacy Fallback'}"
                )
                continue

            if line == "/help":
                print("\nATP Message Format Example:")
                print("  #Mode: Build")
                print("  #Context: Research modern renewable tech")
                print("  #Priority: High")
                print("  #ActionType: Execute")
                print("  #TargetZone: /energy")
                print("  Provide an overview of solar and wind breakthroughs.\n")
                continue

            task_data = build_task_payload(line, strict=strict)
            execute_instruction(
                orchestrator,
                task_data,
                show_routing=show_routing,
                as_json=False,
            )

        except (KeyboardInterrupt, EOFError):
            print("\nSession interrupted. Farewell.")
            break
        except Exception as exc:
            print(f"Error: {exc}")


def main() -> None:
    """Main CLI entry point for ATP-enabled agent interactions."""
    args = parse_atp_cli_args()

    # Initialize Run Logger
    run_logger = init_run_logger()

    # Determine prompt source
    prompt_text = args.instruction or args.prompt
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_file():
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        prompt_text = file_path.read_text(encoding="utf-8")

    # Check for piped stdin if no argument provided
    if not prompt_text and not args.interactive and not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            prompt_text = piped

    # Initialize Orchestrator
    try:
        orchestrator = src.mcp.orchestrator.Orchestrator()
    except Exception as exc:
        logger.error("Failed to initialize Orchestrator: %s", sanitize_for_log(exc))
        print(f"Fatal: Orchestrator failed to boot: {exc}", file=sys.stderr)
        sys.exit(1)

    if prompt_text:
        # One-shot execution
        task_data = build_task_payload(
            prompt_text,
            capability=args.capability,
            agent_name=args.agent,
            title=args.title,
            target_zone=args.target_zone,
            mode=args.mode,
            priority=args.priority,
            strict=args.strict,
        )
        result = execute_instruction(
            orchestrator,
            task_data,
            show_routing=args.show_routing,
            as_json=args.json,
        )
        if result.get("status") == "failed":
            sys.exit(1)
    else:
        # Interactive REPL
        run_interactive_atp_loop(
            orchestrator,
            strict=args.strict,
            show_routing=args.show_routing,
        )


if __name__ == "__main__":
    main()
