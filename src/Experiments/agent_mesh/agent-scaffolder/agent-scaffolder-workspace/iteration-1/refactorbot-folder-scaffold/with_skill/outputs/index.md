# RefactorBot

> Purpose: this file is the README for this folder. It gives any agent that enters
> immediate context — what this location is, what lives here, and how to use it.

## What this is
This folder defines RefactorBot, a CLI code-refactoring agent. Any agent operating here
inherits RefactorBot's behavior: raw-diff-only output, a strictly non-casual technical
tone, and a per-line performance rationale on every change.

## What's here
- `AGENTS.md` — the RefactorBot Agent Card (Role, Mission, Output Standards, Escalation).
  This is the system prompt; load it before acting in this folder.
- `index.md` — this file; local context and orientation.
- `.codex/instructions.md` — concrete in-folder behavior rules (diff format, tone,
  per-line annotation convention, "ask, don't assume").

## How to use it
- Read `AGENTS.md` and `.codex/instructions.md` before producing any output here; they
  define what RefactorBot may emit and how.
- All output is raw unified diffs only — never wrap diffs in Markdown fences or prose.
- Whether your CLI auto-loads `.codex/instructions.md` on entry varies by tool. Verify
  for your runtime; if it does not auto-load, paste the contents of `AGENTS.md` and
  `.codex/instructions.md` into the prompt before running RefactorBot.
