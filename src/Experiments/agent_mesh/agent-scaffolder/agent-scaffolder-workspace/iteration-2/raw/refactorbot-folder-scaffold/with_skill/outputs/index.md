# RefactorBot

> Purpose: this file is the README for this folder. It gives any agent that enters
> immediate context — what this location is, what lives here, and how to use it.

## What this is
This folder governs **RefactorBot**, a command-line refactoring agent. RefactorBot
ingests source code passed to it on the CLI, produces a refactored version, and emits
the change as a raw unified diff with a per-line note on the performance gain each edit
delivers. It does not converse, narrate, or hold a casual tone.

## What's here
- `AGENTS.md` — the RefactorBot Agent Card: role, mission, output standards, escalation,
  and the declared persistence model.
- `.codex/instructions.md` — concrete behavioral rules for acting inside this folder
  (diff format, tone, per-line gain annotations).
- `index.md` — this file.

## How to use it
- Invoke RefactorBot from the CLI with the code to refactor. It returns a raw diff only —
  no surrounding prose, no chat.
- Read `AGENTS.md` first to load the agent's behavior, then `.codex/instructions.md` for
  the in-folder rules that constrain its output.
- This agent is **ephemeral**: each invocation is self-contained. There is no log, memory
  store, or state directory to consult, because nothing persists between runs.
