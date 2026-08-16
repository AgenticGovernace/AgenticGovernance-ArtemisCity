# Docs Project — multi-agent workspace

> Purpose: this file is the README for this folder. It gives any agent that enters immediate
> context — what this location is, what lives here, and how to use it.

## What this is

A documentation project worked by two coordinating agents: a **Writer** (Scribe) that drafts and
revises docs, and a **Reviewer** (Critic) that reviews drafts and returns structured feedback.
They hand work back and forth over the Artemis Transmission Protocol (ATP). The full agent
definitions and coordination rules live in `AGENTS.md`; this file is just the map.

## What's here

- `AGENTS.md` — the two Agent Cards (Writer, Reviewer), the file-based persistence model, the
  ATP communication/handshake rules, and the audit policy. **Read this first.**
- `STATE.md` — the single source of truth for coordination: who owns each doc right now, its
  status, and the current round. Read on entry; update on every handoff.
- `.codex/instructions.md` — concrete behavioral rules for acting inside this folder.
- `docs/` — the documentation drafts. Written only by the Writer. Includes `style-guide.md`,
  the shared standard the Reviewer reviews against.
- `review/feedback/` — one feedback file per review round, written only by the Reviewer.
  See `review/feedback/README.md` for the feedback file format.
- `logs/` — `handoff-log.md` (append-only audit of every handoff) and `reflection.md`
  (cadence summaries from both agents).

## How to use it

1. On entry, read `AGENTS.md`, then `STATE.md` to learn whose turn it is and what's in flight.
2. Act **only** on docs you own in `STATE.md`. The Writer writes `docs/`; the Reviewer writes
   `review/feedback/`. Take ownership before working and release it when you hand off.
3. Every handoff: update `STATE.md`, send an ATP-headed message, and append a line to
   `logs/handoff-log.md`.
4. The loop ends when the Reviewer returns `VERDICT: approved` in a feedback file.
