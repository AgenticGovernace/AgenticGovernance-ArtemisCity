# CompSuite — Audit Agent Workspace

> Purpose: this file is the README for this folder. It gives any agent that enters
> immediate context — what this location is, what lives here, and how to use it.

## What this is

The home of **CompSuite**, an unattended directory-watching audit agent. CompSuite watches
the `voice_logs/` and `outputs/` directories, classifies every file event as
Normal / Warning / Error, escalates only above Warning, and keeps a fully traceable record
of its own actions. This folder holds the agent's definition, its in-folder behavior rules,
and its log/provenance destinations.

## What's here

- `AGENTS.md` — the CompSuite Agent Card: role, mission, boundaries, escalation policy,
  memory, reflection routine, and audit/provenance contract, plus the persistence model.
- `.codex/instructions.md` — concrete behavioral rules for acting inside this folder
  (classification policy, escalation threshold, logging discipline).
- `logs/` — the file-based persistence destination:
  - `daily-<date>.md` — per-action activity log for each day.
  - `escalations-<date>.md` — high-priority log; Warnings recorded here, Errors trigger a
    human alert.
  - `reflection.md` — cadence summaries (every 50 actions or 12 hours).
  - `agent_logs.jsonl` — local mirror of the provenance line items (parent/child `prov_id`s).
  - `README.md` — describes each log file's shape.

## How to use it

- A runner injects `AGENTS.md` + `.codex/instructions.md` as CompSuite's context, points it
  at the watched directories, and lets it run unattended.
- CompSuite reads the latest `logs/daily-*.md` and `logs/reflection.md` on start (its
  memory), then appends new observations; it never modifies anything outside `logs/` and the
  provenance store.
- Provenance is mandatory: every read/write is logged via the atp-provenance-logging skill
  (external `agent_logs`, mirrored locally to `logs/agent_logs.jsonl`). If a provenance write
  fails, CompSuite halts and alerts rather than producing an untraceable observation.
- Persistence tier: **File-based + External provenance.** See `AGENTS.md` → Persistence model.
