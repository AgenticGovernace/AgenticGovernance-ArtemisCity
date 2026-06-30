"""Minimal Artemis City deployment: one agent + the memory bus.

This is the smallest end-to-end slice of the system:
  
  1. An :class:`AgentRegistry` with a single registered agent.
  2. Capability-based routing of a task to that agent.
  3. The agent executing the task.
  4. The :class:`MemoryBus` writing the result through to both stores
  (vector + Obsidian) and then recalling it via the read hierarchy.
  
  Everything runs against temporary SQLite databases and a temporary vault, so
  the example is side-effect free and needs no configuration. Run it with::
    
    python examples/minimal_deployment/run.py
    """
    
    from __future__ import annotations
    
    import shutil
    import sys
    import tempfile
    from pathlib import Path
    
    # Put the repo root on sys.path so the `src` package resolves.
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_REPO_ROOT))
    
    from src.agents.summarizer_agent import SummarizerAgent  # noqa: E402
    from src.integration.agent_registry import AgentRegistry  # noqa: E402
    from src.integration.memory_bus import MemoryBus  # noqa: E402
    from src.mcp.vector_store import LocalVectorStore  # noqa: E402
    from src.obsidian_integration import ObsidianManager  # noqa: E402
    
    SAMPLE_TEXT = (
      "Artemis City is a multi-agent operating system that pairs a Python "
      "orchestration core with an Obsidian-backed memory layer. Agents read tasks "
      "from notes, execute them under governance, and write auditable results back "
      "to the vault while a vector store provides fast semantic recall."
      )
      
      
      def main() -> None:"""Run the minimal deployment demo end to end."""
      workdir = Path(tempfile.mkdtemp(prefix = "artemis_minimal_"))
      vault = workdir / "vault"
      (vault / "Agent Outputs").mkdir(parents = True, exist_ok = True)
      
      try:print("=" * 70)
      print("ARTEMIS CITY — Minimal Deployment (1 agent + memory bus)")
      print("=" * 70)
      
      # 1. Registry with a single agent.
      registry = AgentRegistry(db_path = str(workdir / "agent_registry.db"))
      registry.register_agent(SummarizerAgent())
      print(f"\nRegistered agents: {registry.get_agent_names()}")
      
      # 2. Route a task by required capability.
      task = {
        "task_id":"demo_summary_001", "title":"Summarize the project blurb", "required_capability":"text_summarization", "content":SAMPLE_TEXT,
        }
        agent_name = registry.route_task(task)
        print(f"Task routed to: {agent_name}")
        
        # 3. Execute it.
        agent = registry.get_agent(agent_name)
        result = agent.perform_task(task)
        print(f"\nAgent status : {result['status']}")
        print(f"Summary      : {result['summary']}")
        
        # 4. Write the result through the memory bus, then recall it.
        memory = MemoryBus(ObsidianManager(str(vault)),
        LocalVectorStore(db_path = str(workdir / "vector_store.db")),
        search_dirs = ["Agent Outputs"],
        )
        report_path = "Agent Outputs/summary_report.md"
        report_md = f"# Summary Report\n\n{result['summary']}\n"
        write_info = memory.write_note_with_embedding(report_path, report_md, metadata =
        {
          "agent":agent_name, "task_id":task["task_id"]
          }, )
          print("\nMemory write-through OK "
          f"(total {write_info['total_latency_ms']:.1f}ms)")
          
          recalled = memory.read("Artemis City memory layer", max_results =
          3)
          print(f"Memory recall returned {len(recalled)} hit(s):")
          for hit in recalled:print(f"  - source={hit['source']:<8} score={hit.get('score', 0):.2f} path={hit['path']}")
          
          # Show the agent's standing in the registry.
          scored = registry.get_all_agents_with_scores()[0]
          print(
            f"\nAgent score  : composite={scored['composite_score']:.2f} "
            f"(alignment={scored['alignment']}, accuracy={scored['accuracy']}, "
            f"efficiency={scored['efficiency']})"
            )
            print("\nDone.")
            finally:shutil.rmtree(workdir, ignore_errors = True)
            
            
            if __name__ == "__main__":main()
            
