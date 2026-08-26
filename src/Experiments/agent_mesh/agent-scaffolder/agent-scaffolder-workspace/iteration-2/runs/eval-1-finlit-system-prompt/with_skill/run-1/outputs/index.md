# FinLit Planner

> Purpose: this file is the README for this folder. It gives any agent that enters
> immediate context — what this location is, what lives here, and how to use it.

## What this is

This folder defines the FinLit Planner agent: a friendly budgeting and financial-literacy
coach that helps users build budgets and understand money concepts, while staying firmly
out of specific investment buy/sell advice and other regulated guidance.

## What's here

- `finlit-planner-system-prompt.md` — the agent's system prompt (the Agent Card). This is
  the primary deliverable; load it as the agent's system/persona prompt.
- `AGENTS.md` — the same Agent Card plus the persistence model and scope notes.
- `.codex/instructions.md` — concrete behavior rules for acting inside this folder.

## How to use it

Use `finlit-planner-system-prompt.md` as the system prompt for the agent. The agent runs
at the **Session** persistence tier — it remembers figures within a single conversation
but stores nothing across sessions, so it makes no cross-session memory or audit promises.
There is no `logs/` directory because no durable log destination is in scope.
