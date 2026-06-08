"""Multi-agent workflow: Research -> (memory hand-off) -> Summarize.

Demonstrates how agents collaborate *through shared memory* and how the
Hebbian layer learns from the outcomes:

1. A research task is routed to the ResearchAgent, which produces findings.
2. The findings are written to the memory bus (the shared, auditable store).
3. A summarization task is routed to the SummarizerAgent, which reads the
   research back out of memory and condenses it.
4. Each successful step strengthens a Hebbian agent->task connection, and the
   weight changes are propagated in a single batch via :class:`HebbianSyncService`.

Runs against temporary databases and a temporary vault. Note the ResearchAgent
simulates work with a short sleep, so the demo takes a few seconds. Run with::

    python examples/multi_agent_workflow/run.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from src.agents.research_agent import ResearchAgent  # noqa: E402
from src.agents.summarizer_agent import SummarizerAgent  # noqa: E402
from src.integration.agent_registry import AgentRegistry  # noqa: E402
from src.integration.hebbian_sync import HebbianSyncService  # noqa: E402
from src.integration.memory_bus import MemoryBus  # noqa: E402
from src.mcp.hebbian_weights import HebbianWeightManager  # noqa: E402
from src.mcp.vector_store import LocalVectorStore  # noqa: E402
from src.obsidian_integration import ObsidianManager  # noqa: E402


def main() -> None:
    """Run the research -> summarize pipeline end to end."""
    workdir = Path(tempfile.mkdtemp(prefix="artemis_workflow_"))
    vault = workdir / "vault"
    (vault / "Agent Outputs").mkdir(parents=True, exist_ok=True)

    try:
        print("=" * 70)
        print("ARTEMIS CITY — Multi-Agent Workflow (Research -> Summarize)")
        print("=" * 70)

        registry = AgentRegistry(db_path=str(workdir / "agent_registry.db"))
        registry.register_agent(ResearchAgent())
        registry.register_agent(SummarizerAgent())
        print(f"\nRegistered agents: {registry.get_agent_names()}")

        memory = MemoryBus(
            ObsidianManager(str(vault)),
            LocalVectorStore(db_path=str(workdir / "vector_store.db")),
            search_dirs=["Agent Outputs"],
        )
        hebbian = HebbianWeightManager(db_path=str(workdir / "hebbian_weights.db"))
        # Batch weight-change propagation instead of one write per update.
        sync = HebbianSyncService(sink=lambda batch: None)

        # --- Stage 1: research -------------------------------------------------
        research_task = {
            "task_id": "wf_research_001",
            "title": "Adaptive multi-agent memory systems",
            "topic": "adaptive multi-agent memory systems",
            "keywords": "hebbian,memory bus,governance",
            "required_capability": "document_analysis",
        }
        researcher = registry.route_task(research_task)
        print(f"\n[Stage 1] '{research_task['title']}' -> {researcher}")
        research_result = registry.get_agent(researcher).perform_task(research_task)

        # Hand off via shared memory: write the research findings to the vault.
        findings_md = "# Research Findings\n\n" + research_result["summary"] + "\n\n"
        findings_md += "\n".join(f"- {f}" for f in research_result["findings"])
        memory.write_note_with_embedding(
            "Agent Outputs/research_findings.md",
            findings_md,
            metadata={"agent": researcher, "task_id": research_task["task_id"]},
        )
        _reward(hebbian, sync, researcher, research_task["task_id"])
        print("  findings written to shared memory; Hebbian connection reinforced")

        # --- Stage 2: summarize (reads research back out of memory) -----------
        recalled = memory.read("research findings", max_results=1)
        handed_off = recalled[0]["content"] if recalled else findings_md
        summary_task = {
            "task_id": "wf_summary_001",
            "title": "Summarize the research findings",
            "required_capability": "text_summarization",
            "content": handed_off,
        }
        summarizer = registry.route_task(summary_task)
        print(f"\n[Stage 2] '{summary_task['title']}' -> {summarizer}")
        summary_result = registry.get_agent(summarizer).perform_task(summary_task)
        _reward(hebbian, sync, summarizer, summary_task["task_id"])
        print(f"  summary: {summary_result['summary'][:120]}...")

        # --- Flush batched weight updates & report ----------------------------
        batch = sync.flush_batch()
        net = hebbian.get_network_summary()
        print("\n" + "-" * 70)
        print("Hebbian network after workflow:")
        print(f"  connections      : {net.get('total_connections', 0)}")
        print(f"  average weight   : {net.get('average_weight', 0):.2f}")
        print(f"  success rate     : {net.get('success_rate', 0) * 100:.0f}%")
        print(
            f"  sync batch       : flushed {batch.flushed} update(s) "
            f"in {batch.latency_ms:.2f}ms"
        )
        print("\nDone.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _reward(hebbian, sync, agent_name: str, task_id: str) -> None:
    """Strengthen the agent->task connection and queue the change for sync."""
    old_weight = hebbian.get_weight(agent_name, task_id)
    new_weight = hebbian.strengthen_connection(agent_name, task_id)
    sync.propagate(f"{agent_name}->{task_id}", old_weight, new_weight)


if __name__ == "__main__":
    main()
