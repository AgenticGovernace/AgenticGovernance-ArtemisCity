"""Minimal Artemis City deployment: one agent plus the memory bus.

The demo uses the repository's canonical data and log roots so its registry,
vector, and run metrics are immediately visible to the dashboard API.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from src.agents.summarizer_agent import SummarizerAgent  # noqa: E402
from src.integration.agent_registry import AgentRegistry  # noqa: E402
from src.integration.memory_bus import MemoryBus  # noqa: E402
from src.mcp.vector_store import LocalVectorStore  # noqa: E402
from src.obsidian_integration import ObsidianManager  # noqa: E402
from src.runtime_paths import data_dir, data_path  # noqa: E402
from src.utils.run_logger import init_run_logger  # noqa: E402

SAMPLE_TEXT = (
    "Artemis City is a multi-agent operating system that pairs a Python "
    "orchestration core with an Obsidian-backed memory layer. Agents read tasks "
    "from notes, execute them under governance, and write auditable results back "
    "to the vault while a vector store provides fast semantic recall."
)


def main() -> None:
    """Run the minimal deployment demo end to end."""
    vault = Path(
        data_path(
            "minimal_vault",
            env_var="ARTEMIS_MINIMAL_VAULT",
        )
    )
    (vault / "Agent Outputs").mkdir(parents=True, exist_ok=True)
    run_logger = init_run_logger()

    try:
        print("=" * 70)
        print("ARTEMIS CITY — Minimal Deployment (1 agent + memory bus)")
        print("=" * 70)

        registry = AgentRegistry()
        registry.register_agent(SummarizerAgent())
        print(f"\nRegistered agents: {registry.get_agent_names()}")

        task = {
            "task_id": "demo_summary_001",
            "title": "Summarize the project blurb",
            "required_capability": "text_summarization",
            "content": SAMPLE_TEXT,
        }
        agent_name = registry.route_task(task)
        print(f"Task routed to: {agent_name}")

        agent = registry.get_agent(agent_name)
        result = agent.perform_task(task)
        print(f"\nAgent status : {result['status']}")
        print(f"Summary      : {result['summary']}")

        memory = MemoryBus(
            ObsidianManager(str(vault)),
            LocalVectorStore(),
            search_dirs=["Agent Outputs"],
        )
        report_path = "Agent Outputs/summary_report.md"
        report_md = f"# Summary Report\n\n{result['summary']}\n"
        write_info = memory.write_note_with_embedding(
            report_path,
            report_md,
            metadata={"agent": agent_name, "task_id": task["task_id"]},
        )
        print(
            "\nMemory write-through OK "
            f"(total {write_info['total_latency_ms']:.1f}ms)"
        )

        recalled = memory.read("Artemis City memory layer", max_results=3)
        print(f"Memory recall returned {len(recalled)} hit(s):")
        for hit in recalled:
            print(
                f"  - source={hit['source']:<8} "
                f"score={hit.get('score', 0):.2f} path={hit['path']}"
            )

        scored = registry.get_all_agents_with_scores()[0]
        print(
            f"\nAgent score  : composite={scored['composite_score']:.2f} "
            f"(alignment={scored['alignment']}, accuracy={scored['accuracy']}, "
            f"efficiency={scored['efficiency']})"
        )
        run_logger.finalize_run(
            status="completed",
            summary={"agent": agent_name, "task_id": task["task_id"]},
        )
        print(f"\nPersistent metrics: {data_dir()}")
        print("Done.")
    except Exception as exc:
        run_logger.finalize_run(status="failed", summary={"error": str(exc)})
        raise


if __name__ == "__main__":
    main()
