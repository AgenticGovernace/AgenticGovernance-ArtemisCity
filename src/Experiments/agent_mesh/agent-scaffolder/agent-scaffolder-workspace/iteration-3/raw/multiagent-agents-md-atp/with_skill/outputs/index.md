# Docs Project — Writer + Reviewer Workspace

> Purpose: this file is the README for this folder. It gives any agent that enters
> immediate context — what this location is, what lives here, and how to use it.

## What this is

This folder is a multi-agent documentation project. Two agents share it: **Scribe** (the
Writer) drafts and revises docs, and **Ledger** (the Reviewer) critiques drafts and gates
them for publish. They coordinate over the Artemis Transmission Protocol, recording each
hand-off in `handoff.md`. The full behavior spec for both agents is in `AGENTS.md`.

## What's here

- `AGENTS.md` — the two agent cards (Writer + Reviewer), the file-based persistence model,
  the ATP communication layer, and the (optional, off-by-default) provenance pointer.
- `.codex/instructions.md` — concrete in-folder behavior rules for acting here.
- `drafts/` — Writer-owned. Document drafts (Writer writes, Reviewer reads only).
- `reviews/` — Reviewer-owned. Structured review files keyed to drafts (Reviewer writes,
  Writer reads only).
- `handoff.md` — the shared coordination ledger; both agents append ATP-headed entries here.
- `logs/` — per-agent activity logs and reflection logs (the file-based persistence backend).

## How to use it

- **Writer (Scribe):** read the latest `reviews/<doc>.review.md` and `handoff.md`, address
  open notes by ID, write/revise the file in `drafts/`, then append a `RevisionSubmitted`
  (or `ReviewRequest`) entry to `handoff.md`.
- **Reviewer (Ledger):** read the draft in `drafts/` and `handoff.md`, ack, write the
  review in `reviews/`, assign a verdict, then append a `ReviewReturned` entry to
  `handoff.md`.
- **Ownership:** each agent writes only its own directory plus its own logs and appends to
  `handoff.md`; neither edits the other's files. This keeps the review loop race-free.
- A document is done when the Reviewer records an `approve` verdict (an `Approved` entry in
  `handoff.md`).
