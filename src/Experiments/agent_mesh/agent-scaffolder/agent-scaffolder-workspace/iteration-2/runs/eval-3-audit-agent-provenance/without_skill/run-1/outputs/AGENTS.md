# AGENTS.md — CompSuite

> Operating contract for **CompSuite**, an unattended file-audit agent.
> Read this file in full before taking any action. It defines what CompSuite
> watches, how it classifies events, when it is allowed to escalate, and the
> provenance guarantees every action must satisfy.

---

## 1. Mission

CompSuite is a **compliance / audit watcher**. It runs unattended and observes
two directories:

- `voice_logs/` — incoming voice transcripts / recordings metadata.
- `outputs/` — generated artifacts produced by other tooling.

For **every** file event (create, modify, move, delete) in those trees,
CompSuite:

1. **Classifies** the event into exactly one severity: `Normal`, `Warning`,
   or `Error`.
2. **Records** the event and its classification to the daily audit log.
3. **Tracks provenance**: every read and every write CompSuite performs is
   logged as a traceable action with a unique id, a parent run id, and a
   content hash, so the chain "who/what touched which bytes when" is fully
   reconstructable.
4. **Escalates only when warranted** (see §4).

CompSuite never modifies the files it watches. It is read-only with respect to
`voice_logs/` and `outputs/`; the only things it writes are its own logs,
provenance ledger, and reflection summaries.

---

## 2. Severity Classification

Every event is assigned exactly one of three levels.

| Severity  | Meaning                                                                     | Example triggers (default rules)                                                                                                                                                         |
| --------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Normal`  | Expected, benign activity. The steady state.                                | A new `.wav`/`.json` transcript appears; an output file is written with a known, allowed extension.                                                                                      |
| `Warning` | Unusual but not necessarily wrong. Worth noting; **do not** escalate.       | Unexpected file extension; zero-byte file; file modified unusually frequently; deletion of an output.                                                                                    |
| `Error`   | A real problem or policy violation. **This is the only escalatable level.** | Write/event in a path outside the watched roots; a forbidden/dangerous extension (e.g. `.exe`, `.sh`); a watched file becomes unreadable / permissions broken; classifier itself failed. |

Classification rules live in `config/compsuite.toml` so they can be tuned
without code changes. The mapping above is the documented default.

---

## 3. Severity Ordering

```
Normal (0)  <  Warning (1)  <  Error (2)
```

This ordering is the basis for the escalation gate in §4. "Above Warning"
means strictly greater than `Warning` — i.e., `Error` only.

---

## 4. Escalation Policy (the core rule)

> **CompSuite must only escalate above Warning.**

Interpretation, made explicit so there is no ambiguity:

- `Normal` → log only. Never escalate.
- `Warning` → log (and surface in the daily summary). **Never escalate.**
- `Error` → log **and escalate**.

"Escalate" = invoke the configured escalation sink (default: append a record to
`logs/escalations.log` and emit a high-visibility marker line; an
operator-supplied webhook/command may be wired in via `config`). The gate is a
single chokepoint in code (`should_escalate`) so the policy cannot be bypassed
accidentally:

```
should_escalate(severity) == (severity_rank(severity) > severity_rank("Warning"))
```

If a future rule introduces a new level, it escalates **iff** its rank exceeds
Warning's. There is no other path to escalation.

---

## 5. Unattended Operation & Daily Logs

CompSuite is designed to run continuously with no human in the loop.

- **Run loop:** it watches the two roots (polling by default — no third-party
  dependency required; an optional `watchdog` backend can be enabled) and
  processes events as they arrive.
- **Daily logs:** all audit records are written to
  `logs/audit-YYYY-MM-DD.log` (one file per UTC day). The file rolls over
  automatically at the day boundary; no restart is needed.
- **Crash safety:** logs and the provenance ledger are append-only and flushed
  per record, so an abrupt termination loses at most the in-flight event.
- **Idempotent restart:** on startup CompSuite reads its last checkpoint
  (`logs/.state.json`) so re-scanning an already-seen tree does not double-count
  actions.

---

## 6. Reflection Summaries

Roughly **every 50 actions** (configurable: `reflection.every_n_actions`),
CompSuite emits a **reflection summary** to
`logs/reflections/reflection-<seq>-<timestamp>.md`.

A reflection captures, for the window since the last reflection:

- counts by severity (Normal / Warning / Error),
- the number of escalations fired,
- the busiest watched paths,
- any anomalies (e.g., a spike in Warnings),
- a short self-check: _"Did I escalate exactly the Errors and nothing below?"_

Reflections are for the operator and for the agent's own drift-detection. They
never themselves escalate.

---

## 7. Action-Level Provenance

Every discrete thing CompSuite does is an **action** with a provenance record.
This is non-negotiable: **every read and every write is traceable.**

Each action record (NDJSON line in `logs/provenance/provenance-YYYY-MM-DD.ndjson`)
contains:

| Field           | Description                                                            |
| --------------- | ---------------------------------------------------------------------- |
| `action_id`     | Unique id for this action (UUID4).                                     |
| `parent_run_id` | The id of the CompSuite run/session that owns this action.             |
| `seq`           | Monotonic action counter within the run.                               |
| `ts`            | UTC ISO-8601 timestamp.                                                |
| `verb`          | One of `READ`, `WRITE`, `CLASSIFY`, `ESCALATE`, `REFLECT`, `SCAN`.     |
| `target`        | Absolute path (or logical sink name) the action touched.               |
| `severity`      | Classification attached to the originating event, if any.              |
| `sha256`        | Content hash of the bytes read or written (`null` for non-IO actions). |
| `bytes`         | Size in bytes for IO actions.                                          |
| `detail`        | Free-form note (rule matched, reason for severity, etc.).              |

Guarantees:

- **No silent IO.** Reads and writes go through `provenance.read_file` /
  `provenance.write_file` wrappers, which are the _only_ sanctioned IO paths.
  Anything bypassing them is a bug.
- **Linkage.** `parent_run_id` ties every action back to one run; `seq` orders
  them; `action_id` identifies them individually.
- **Tamper-evidence.** Each record carries the `sha256` of the bytes involved,
  so after the fact you can verify the file that was read/written matches what
  the log claims.

---

## 8. Directory Layout

```
.
├── AGENTS.md                     # This file — the operating contract.
├── README.md                     # Human quick-start.
├── compsuite.py                  # Entry point / run loop.
├── compsuite/                    # Package.
│   ├── __init__.py
│   ├── provenance.py             # Action ids, sanctioned IO wrappers, ledger.
│   ├── classifier.py             # Event → Normal/Warning/Error.
│   ├── escalation.py             # The single escalation gate + sinks.
│   ├── reflection.py             # Periodic reflection summaries.
│   └── watcher.py                # Watch loop over the two roots.
├── config/
│   └── compsuite.toml            # Watched roots, rules, thresholds.
├── logs/                         # All agent output (created at runtime).
│   ├── audit-YYYY-MM-DD.log
│   ├── escalations.log
│   ├── provenance/provenance-YYYY-MM-DD.ndjson
│   ├── reflections/reflection-*.md
│   └── .state.json               # Checkpoint for idempotent restart.
├── requirements.txt
└── .gitignore
```

---

## 9. Invariants (must always hold)

1. **Read-only on watched data.** CompSuite never writes inside `voice_logs/`
   or `outputs/`.
2. **One classification per event**, drawn from exactly {Normal, Warning, Error}.
3. **Escalate iff severity rank > Warning.** No Normal or Warning ever escalates.
4. **Every IO action is in the provenance ledger** with a content hash.
5. **Daily log rollover** happens on the UTC day boundary without restart.
6. **A reflection is emitted every N actions** (default 50) and on clean
   shutdown.

---

## 10. Quick Reference

- **What does it watch?** → `voice_logs/` and `outputs/` (from `config`).
- **What can it write?** → only `logs/**`.
- **When does it escalate?** → only on `Error` (rank > Warning).
- **Where are the audit records?** → `logs/audit-YYYY-MM-DD.log`.
- **How do I trace a read/write?** → `logs/provenance/provenance-YYYY-MM-DD.ndjson`.
- **How often does it reflect?** → every ~50 actions → `logs/reflections/`.
