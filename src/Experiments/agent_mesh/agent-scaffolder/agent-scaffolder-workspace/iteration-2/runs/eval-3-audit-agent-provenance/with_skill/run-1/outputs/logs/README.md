# logs/ — CompSuite log destination

This directory is the file-based persistence destination referenced by the CompSuite
Agent Card (`../AGENTS.md`). CompSuite writes here; it never modifies anything outside it.

## Files CompSuite maintains here

- `audit-<YYYY-MM-DD>.md` — the daily activity log. One file per day. Every observed
  file event and its classification (`Normal` / `Warning` / `Error`) is appended here
  with input, output, and status.
- `summary-<YYYY-MM-DD>.md` — the reflection summary. Written every ~50 logged actions
  or every 12 hours (whichever comes first). Contains a severity rollup since the last
  summary and a note on any boundary drift.
- `escalations.md` — high-priority log. `Error`-level events (above the `Warning`
  threshold) are appended here and surfaced to a human operator.

## Note on provenance

These files are the human-readable mirror. The authoritative, line-item action history
lives in the external provenance store (`agent_logs`, via `$PROVENANCE_SERVICE_URL`) per
the atp-provenance-logging skill.
