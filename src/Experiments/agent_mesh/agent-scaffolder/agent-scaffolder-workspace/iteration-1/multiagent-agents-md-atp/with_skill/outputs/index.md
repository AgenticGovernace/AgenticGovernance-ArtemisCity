# Docs Project (multi-agent)

> Purpose: this file is the README for this folder. It gives any agent that enters
> immediate context — what this location is, what lives here, and how to use it.

## What this is
This folder is the root of a **multi-agent documentation project**. Two agents operate
here: a **Writer** (Scribe) that drafts and revises docs, and a **Reviewer** (Arbiter)
that critiques them and gates publication. They coordinate via the Artemis Transmission
Protocol; the handoff loop is defined in `AGENTS.md`.

## What's here
- `AGENTS.md` — the Agent Cards for both Writer and Reviewer, plus the ATP communication
  loop that links them. Read this first to know which agent you are and how to hand off.
- `.codex/instructions.md` — concrete in-folder behavior rules (style, file conventions,
  the draft→review→publish flow, "ask, don't assume").
- `index.md` — this file.
- `docs/drafts/` — work-in-progress docs owned by the Writer (assumed location).
- `docs/published/` — approved docs; only the Reviewer authorizes moves here (assumed
  location).

## How to use it
1. On entry, read `AGENTS.md` to determine your role (Writer or Reviewer) and the handoff
   contract between the two agents.
2. Read `.codex/instructions.md` for the style and file conventions that apply while
   working in this folder.
3. Keep drafts in `docs/drafts/` until the Reviewer issues `VERDICT: approve`; only then
   does a doc move to `docs/published/`.
4. Use an ATP header on every cross-agent handoff so the recipient knows the action type
   (`review` / `revise` / `clarify` / `approve` / `publish`) and target.
