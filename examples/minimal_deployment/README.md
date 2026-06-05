# Minimal Deployment

The smallest end-to-end slice of Artemis City: a single agent plus the memory
bus.

```bash
python examples/minimal_deployment/run.py
```

## What it does

1. Creates an `AgentRegistry` and registers one `SummarizerAgent`.
2. Routes a task to it by `required_capability` (`text_summarization`).
3. Executes the task.
4. Writes the result through the `MemoryBus` (vector store + Obsidian vault),
   then recalls it via the read hierarchy (exact → keyword → vector).

Everything uses temporary SQLite databases and a temporary vault, so there is
nothing to configure and no files are left behind.

## Expected output (abridged)

```
Registered agents: ['Summarizer Agent']
Task routed to: Summarizer Agent
Agent status : success
Summary      : Artemis City is a multi-agent operating system ...
Memory write-through OK (total 3.2ms)
Memory recall returned 2 hit(s):
  - source=keyword  score=1.00 path=Agent Outputs/summary_report.md
  - source=vector   score=0.87 path=Agent Outputs/summary_report.md
Agent score  : composite=0.50 (alignment=0.5, accuracy=0.5, efficiency=0.5)
```
