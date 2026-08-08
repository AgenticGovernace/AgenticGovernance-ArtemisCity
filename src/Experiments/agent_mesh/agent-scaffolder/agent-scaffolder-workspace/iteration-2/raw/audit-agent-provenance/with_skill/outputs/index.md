# CompSuite — Audit Agent Workspace

> Purpose: this file is the README for this folder. It gives any agent that enters
> immediate context — what this location is, what lives here, and how to use it.

## What this is
This folder defines and houses **CompSuite**, an unattended, observe-and-log audit agent
that watches the `voice_logs/` and `outputs/` directories, classifies each file event as
`Normal` / `Warning` / `Error`, escalates only above `Warning`, and keeps full
action-level provenance. The agent never modifies the systems it watches — it only reads
and logs.

## What's here
- `AGENTS.md` — the CompSuite Agent Card (Role, Purpose, Mission Scope, Boundaries,
  Escalation Policy, Memory, Reflection Routine, Audit & Provenance, Version) plus the
  stated persistence model and the pointer to the provenance skill.
- `.codex/instructions.md` — concrete behavioral rules for acting inside this folder
  (classification logic, the observe-only boundary, the logging/provenance contract).
- `logs/` — the log destination the Agent Card references. Holds:
  - `audit-<YYYY-MM-DD>.md` — the daily activity log (all classifications).
  - `summary-<YYYY-MM-DD>.md` — the reflection summary, written every ~50 actions or
    every 12 hours (severity rollup since the last summary).
  - `escalations.md` — high-priority log; `Error`-level events are appended here and
    surfaced to a human.

## How to use it
- CompSuite runs unattended. On startup it reads the latest `logs/audit-*.md` and
  `logs/summary-*.md` to recover what it has already seen, then resumes watching.
- The authoritative action history is the external provenance store (`agent_logs`); the
  files in `logs/` are the human-readable mirror.
- To change what is watched or how events are classified, edit `.codex/instructions.md`
  and the Mission Scope in `AGENTS.md` together.

## Assumptions made during scaffolding
- "Watch" means recursive monitoring of file create / modify / delete / move /
  permission-change events under each watched directory.
- "Daily logs" = one dated log file per day under `logs/`.
- "Every 50 actions or so" = a summary every 50 logged actions, with a 12-hour
  fallback so a quiet period still produces a periodic summary.
- "Above Warning" = only `Error` escalates (Normal and Warning are logged, not paged).
- "Full action-level provenance" = the rigorous atp-provenance-logging path (parent +
  child `prov_id`s in `agent_logs`, halt-on-logging-failure), since the user wants every
  read/write traceable. This presumes a reachable provenance service.
- CompSuite is standalone (no other agents), so the ATP communication layer is omitted.
