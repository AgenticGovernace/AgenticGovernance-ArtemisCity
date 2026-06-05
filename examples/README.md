# Artemis City — Examples

Three small, self-contained programs that exercise the real `src/` APIs end to
end. Each runs against **temporary** SQLite databases and a temporary vault, so
they need no configuration and leave no artifacts behind.

Run any example from the repo root:

```bash
python examples/minimal_deployment/run.py
python examples/multi_agent_workflow/run.py
python examples/governance_demo/run.py
```

| Example | What it shows | Key modules |
|---|---|---|
| [`minimal_deployment/`](minimal_deployment/) | The smallest slice: register one agent, route a task by capability, execute it, and write/recall the result through the memory bus. | `AgentRegistry`, `MemoryBus`, `LocalVectorStore` |
| [`multi_agent_workflow/`](multi_agent_workflow/) | Research → Summarize pipeline where agents collaborate **through shared memory**, with Hebbian reinforcement and batched weight propagation. | `AgentRegistry`, `MemoryBus`, `HebbianWeightManager`, `HebbianSyncService` |
| [`governance_demo/`](governance_demo/) | Sandbox whitelist enforcement → 3-strike quarantine → approval tiers (auto/monitored/human) → checkpoint + rollback. | `AgentSandbox`, `SelfUpdateGovernor`, `CheckpointStore`, `RollbackManager` |

## Requirements

Install the runtime dependencies first (the examples import the `src` package,
which pulls in the agent and memory layers):

```bash
make install        # or: pip install -r requirements.txt
```

## Notes

- The `multi_agent_workflow` example uses the real `ResearchAgent`, which
  simulates work with a short randomized sleep — expect it to take a few seconds.
- Every example cleans up its temporary working directory on exit, including on
  error.
