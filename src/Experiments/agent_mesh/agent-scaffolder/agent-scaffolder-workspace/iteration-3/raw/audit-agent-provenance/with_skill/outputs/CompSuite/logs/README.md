# logs/ — CompSuite persistence destination

This directory is the **file-based** half of CompSuite's persistence model (the other half is
the external provenance store). Every layer the Agent Card promises writes here, so none of
those promises are empty ceremony.

## Files

- **`daily-<date>.md`** — per-action activity log, one per day. Every observed file event is
  appended as a line: timestamp, path, event type, classification (Normal/Warning/Error),
  status, and the `prov_id` of the matching provenance entry. Example file:
  `daily-2026-06-16.md`.
- **`escalations-<date>.md`** — high-priority log. **Warning** events are recorded here for
  review; **Error** events (above the escalation threshold) are recorded here _and_ trigger a
  human alert. Normal events never appear here.
- **`reflection.md`** — append-only reflection log. CompSuite writes a summary **every 50
  actions or every 12 hours, whichever comes first**: event count since last summary, rollup
  by severity, escalations raised, and a drift check. This is the destination that makes the
  Reflection cadence real.
- **`agent_logs.jsonl`** — newline-delimited local mirror of the provenance line items
  (parent prompt + child read/write/execute/tool-call entries, each with `prov_id` and
  `parent_prov_id`). The external provenance service is the source of truth and the
  halt-on-failure trigger; this mirror keeps the trace inspectable on disk.

## Conventions

- Dates are ISO `YYYY-MM-DD`.
- CompSuite only ever **appends** to these files. It never modifies watched directories.
- Provenance entries log paths and metadata only — never secrets or file contents.
