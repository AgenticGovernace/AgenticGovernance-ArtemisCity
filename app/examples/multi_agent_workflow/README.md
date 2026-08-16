# Multi-Agent Workflow

A two-stage pipeline showing agents collaborating **through shared memory**,
with Hebbian learning recording the outcomes.

```bash
python examples/multi_agent_workflow/run.py
```

## Flow

```
research task ──▶ ResearchAgent ──▶ findings written to MemoryBus
                                          │
                                          ▼
summary task  ──▶ SummarizerAgent ◀── reads findings back from MemoryBus
                                          │
                       each success strengthens a Hebbian agent→task link,
                       and the weight changes flush as one HebbianSyncService batch
```

## What it demonstrates

- **Capability routing** to two different agents from one registry.
- **Memory-mediated hand-off**: the summarizer consumes the researcher's output
  from the shared store rather than via a direct call.
- **Hebbian reinforcement** of successful agent→task connections.
- **Batched propagation** of weight changes through `HebbianSyncService`
  (`queue → flush_batch`) instead of one write per change.

## Note

The `ResearchAgent` simulates work with a short randomized sleep, so this
example takes a few seconds to complete. The workflow uses the same root
`data/` databases as the API; its small example vault is retained at
`data/workflow_vault/` so the full run remains inspectable.
