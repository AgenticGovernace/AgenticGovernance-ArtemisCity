# RefactorBot

> Purpose: this file is the README for this folder. It gives any agent that
> enters immediate context — what this location is, what lives here, and how to
> use it.

## What this is
This folder is the home of **RefactorBot**, a standalone CLI code-refactoring
agent. RefactorBot takes source code given on the command line and returns
behavior-preserving refactors as raw diffs, annotating each changed line with
its expected performance gain. It operates statelessly: nothing persists between
invocations.

## What's here
- `AGENTS.md` — RefactorBot's Agent Card: role, mission, output standards,
  escalation rules, and the stated persistence model (Ephemeral).
- `.codex/instructions.md` — concrete behavioral rules for acting inside this
  folder (the current-task layer).
- `index.md` — this file.

## How to use it
- Read `AGENTS.md` first to understand what RefactorBot will and will not do.
- The hard output contract: RefactorBot emits **a raw unified diff only**, with
  a **per-line performance rationale** for every change, in a **formal tone** —
  no casual language, no prose outside the diff.
- RefactorBot is Ephemeral by design. There are no logs, memory files, or
  reflection logs in this folder, and none should be expected. If you add a
  persistent runtime, update `AGENTS.md` per the agent-scaffolder skill before
  promising memory, reflection cadence, or audit.
