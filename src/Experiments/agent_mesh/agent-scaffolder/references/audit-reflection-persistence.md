# Audit, Reflection & Persistence — the detailed playbook

Read this when an agent needs to remember, reflect on a cadence, or log its actions for
audit. The governing idea: **memory, reflection, and audit are only real if there is a
place to keep them.** Pick the persistence tier first, then add only the layers that tier
can support.

## Contents
1. Persistence tiers in depth
2. Reflection patterns
3. Audit & provenance integration (atp-provenance-logging)
4. Worked example: an audit agent

---

## 1. Persistence tiers in depth

| Tier | State lives in | Memory you can promise | Reflection you can promise | Audit you can promise |
|------|----------------|------------------------|----------------------------|-----------------------|
| **Ephemeral** | nowhere (single turn/session) | none | one-line inline self-check after a major output | none |
| **Session** | the live context window | recall earlier turns this session | a session-end summary | in-session notes only |
| **File-based** | files the agent reads/writes (logs, `index.md`, `.csv`/`.qmd`) | read prior state/log files on entry | append summaries to a reflection log on a cadence | write per-action log files; escalate via a high-priority log |
| **External service / DB** | a provenance service or database | query the store | persist reflections as records | full line-item provenance — see §3 |

Why this matters: the source notes call Memory and Reflection "optional if persistent
memory exists." The common failure is to keep them anyway — e.g., telling an ephemeral
agent to "recall previous outputs" or "summarize every 50 actions." The agent can't, so
it either ignores the rule (eroding trust in the whole card) or *pretends* it did
(hallucinated continuity). Always state the tier in `AGENTS.md` so the included layers
are justified.

**Detecting the tier:** ask, or infer from the runtime. A bare chat turn is Ephemeral. A
Codex-CLI / notebook / wrapper that re-injects files is File-based. A setup with the
provenance service (or a database) is External.

---

## 2. Reflection patterns

Define reflection on three axes — trigger, content, destination.

**Trigger**
- *Always:* after every major output, a one-sentence self-check. This needs no
  persistence and belongs even in ephemeral agents.
- *Cadence (persistent only):* every N actions (e.g., 50) or every T hours (e.g., 12).
  Mirrors a monitoring agent's summary routine.

**Content**
- What was attempted.
- Whether assumptions were necessary (and which).
- Whether anything drifted from the mission or boundaries.
- For audit agents: a rollup of events by severity since the last summary.

**Destination**
- Ephemeral/Session → inline in the response (or a session-end note).
- File-based → append to a reflection/summary log (e.g., `logs/reflection.md`).
- External → write a reflection record (and, with provenance, a line item).

Rule of thumb: a cadence with no destination is theater. If there's nowhere to write the
summary, keep only the inline self-check.

---

## 3. Audit & provenance integration

Add an **Audit / Provenance** layer when the agent (a) takes consequential actions you
need to trace, (b) runs unattended or long, or (c) coordinates with other agents.

Two intensities:

**Lightweight (file-based).** Log each action to a file with input, output, status, and
timestamp; define an escalation threshold (e.g., escalate only above `Warning`). Good for
a single monitoring agent.

**Rigorous (atp-provenance-logging skill).** Use when every action must be traceable to
the prompt that caused it. The skill's contract:

- Mint **one parent `prov_id`** per ATP prompt; embed it in the ATP header
  (`[[Special Instructions]] prov_id=<uuid>`).
- Log the prompt itself as the root line item (`parent_prov_id: null`).
- For **every** subsequent action (read / write / execute / tool call), create a **child**
  entry with a new `prov_id` and `parent_prov_id` set to the parent, in `agent_logs`.
- Log errors as child entries with `status: "error"`, lineage preserved.
- Log a final `atp_response` entry.
- **Halt-and-alert** if any log write fails — outputs without provenance are invalid.
- It expects a reachable provenance service (`$PROVENANCE_SERVICE_URL`); don't log secrets.

Only wire in the rigorous path when that strictness (and the service dependency) is
actually wanted. Reference the skill from `AGENTS.md` rather than inlining its full rules.

**Observe-and-log archetype:** monitoring/audit agents observe and log but **never
mutate**. Make that a hard boundary in the card ("DO NOT edit, delete, or modify files;
observe and log only").

---

## 4. Worked example: an audit agent

User intent: "Watch `voice_logs/` and `outputs/`, classify file events Normal/Warning/Error,
escalate only above Warning, run unattended, write daily logs, summarize every 50 actions,
and trace every action."

- **Tier:** File-based (daily logs) + External provenance (trace every action).
- **Card shape:** `audit-agent-card.template.md`.
- **Boundaries:** observe-and-log only; never modify.
- **Escalation Policy:** escalate to a human only above `Warning`.
- **Reflection Routine:** summary every 50 actions or 12 hours → `logs/summary-<date>.md`.
- **Audit & Provenance:** per-action file logs *plus* a reference to atp-provenance-logging
  for parent/child `prov_id`s in `agent_logs`.
- **Scaffold adds** a `logs/` directory as the destination the card references.

This produces an agent whose promises (remember, summarize, log) all map to a real place
to keep them — no hallucinated continuity.
