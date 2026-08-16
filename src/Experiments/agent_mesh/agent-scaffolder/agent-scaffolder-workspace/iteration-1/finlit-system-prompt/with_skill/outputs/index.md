# FinLit Planner

> Purpose: this file is the README for this folder. It gives any agent that enters
> immediate context — what this location is, what lives here, and how to use it.

## What this is
This folder defines the FinLit Planner agent: a friendly financial-literacy and
budgeting coach that helps users build budgets and understand personal-finance concepts,
while explicitly never giving specific investment buy/sell advice.

## What's here
- `system-prompt.md` — the full system prompt (Agent Card) for FinLit Planner, built from
  the 6-layer formula: Role, Mission, Output Standards, Escalation Rules, Memory,
  Reflection.
- `AGENTS.md` — the agent definition (same Agent Card) plus notes on how this agent fits
  into a project.
- `.codex/instructions.md` — concrete behavioral rules for acting inside this folder
  (tone, budget format, the no-investment-advice guardrail).

## How to use it
- To deploy the agent, load `system-prompt.md` as the agent's system prompt.
- The folder's `index.md` and `.codex/instructions.md` are the local context layer.
  Confirm whether your runtime auto-loads these on folder entry; some CLIs read
  `instructions.md` automatically, others need the content pasted into the prompt.
- Scope cascade: global/personal defaults  <  project-wide rules  <  this folder's
  `index.md` / `.codex/instructions.md`.
