# logs/ — Relay offline mirror & tier-3 fallback

This directory is the **fallback** persistence destination referenced by the Relay Agent
Card (`../AGENTS.md`). Relay's primary, authoritative state lives elsewhere:

- **Memory + reflections** → Relay's **Notion page** (tier 1 via the ramble server, tier 2
  via the Notion MCP).
- **Action audit history** → the **provenance store** (`agent_logs`, via
  `$PROVENANCE_SERVICE_URL`), per the atp-provenance-logging skill.

These local files are written only when those services are unreachable (**tier 3**), and
otherwise serve as a human-readable offline mirror. Relay writes here; it never modifies
anything outside this folder.

## Files Relay maintains here (tier-3 fallback only)

- `reflection.md` — appended reflection write-ups, used when neither the ramble server nor
  the Notion MCP can be reached. Each entry follows the reflection format in the
  agent-scaffolder skill's `references/notion-memory.md` (Attempted / Assumptions / Drift
  check / Events rollup / Next). When connectivity returns, these should be reconciled up
  to the Notion page.
- `actions.ndjson` — line-item action log (one JSON object per line: timestamp, action
  type, target/zone, input summary, output summary, status, `prov_id`, `parent_prov_id`),
  written only if the provenance service is down. This is the local stand-in for
  `agent_logs`; reconcile to the provenance store when it is reachable.

## Note on the halt rule

Relay's audit contract is **halt-and-alert if a log write fails** (atp-provenance-logging).
Falling back to `actions.ndjson` here is acceptable degradation only while the provenance
service is unreachable; if even the local write fails, Relay halts rather than acting
without any record. An action taken with no recorded provenance entry anywhere is invalid.
