# CompSuite

An **unattended file-audit agent**. CompSuite watches your `voice_logs/` and
`outputs/` directories, classifies every file event as **Normal / Warning /
Error**, **escalates only above Warning** (i.e., Errors only), writes **daily
logs**, emits a **reflection summary every ~50 actions**, and keeps
**action-level provenance** so every read and write it performs is traceable.

The full operating contract is in [`AGENTS.md`](./AGENTS.md). This README is the
quick start.

## Requirements

- Python **3.11+** (uses the stdlib `tomllib`). On 3.10 and earlier, install
  `tomli` (see `requirements.txt`).
- No other dependencies for the default poll-based watcher.

## Quick start

```bash
# 1. (optional) confirm the policy invariants hold on your machine
python compsuite.py selftest

# 2. see the resolved configuration
python compsuite.py config

# 3. run one scan/diff/process cycle (good for trying it out)
python compsuite.py scan

# 4. run unattended (daemon). Ctrl-C triggers a clean shutdown + final reflection.
python compsuite.py run

# bounded run for testing — stop after 5 poll cycles:
python compsuite.py run --cycles 5
```

On first start CompSuite creates the watched trees (`voice_logs/`, `outputs/`)
and the `logs/` tree if they don't exist.

## What it watches and what it writes

| Watched (read-only) | Written by CompSuite                           |
| ------------------- | ---------------------------------------------- |
| `voice_logs/`       | `logs/audit-YYYY-MM-DD.log`                    |
| `outputs/`          | `logs/escalations.log`                         |
|                     | `logs/provenance/provenance-YYYY-MM-DD.ndjson` |
|                     | `logs/reflections/reflection-*.md`             |
|                     | `logs/.state.json` (restart checkpoint)        |

CompSuite **never writes inside the watched trees** — it is read-only on your
data.

## Classification (Normal / Warning / Error)

| Severity  | When                                                                                                                          |
| --------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `Normal`  | Expected file with an allowed extension; the steady state.                                                                    |
| `Warning` | Unexpected extension, zero-byte file, or a deletion. **Logged, never escalated.**                                             |
| `Error`   | Path outside the watched roots, a forbidden/executable extension, an unreadable file, or a classifier failure. **Escalated.** |

Rules are data-driven in [`config/compsuite.toml`](./config/compsuite.toml)
(`[classification]`).

## Escalation policy

> **CompSuite escalates only above Warning.**

Severities are ranked `Normal (0) < Warning (1) < Error (2)`. The gate
(`compsuite/escalation.py::should_escalate`) escalates a severity **iff its rank
is strictly greater than Warning's** — so only **Error** escalates; Normal and
Warning never do. This is a single chokepoint so it can't be bypassed by
accident. Tune (or, deliberately, lower) the threshold via
`[escalation].threshold`.

Escalations append to `logs/escalations.log` and, optionally, run an operator
command (`[escalation].sinks = ["log", "command"]` + a `command` template).

## Daily logs & unattended operation

- One audit log per UTC day: `logs/audit-YYYY-MM-DD.log` (tab-separated:
  `timestamp  severity  kind  path  escalated?  reason`). Rolls over at the day
  boundary with no restart.
- Append-only and flushed per record (`[logging].flush_each_record`), so an
  abrupt kill loses at most the in-flight event.
- A checkpoint (`logs/.state.json`) makes restarts idempotent and preserves the
  run id across restarts.

## Reflection summaries

Every `[reflection].every_n_actions` actions (default **50**) — and on clean
shutdown — CompSuite writes a markdown reflection to `logs/reflections/`. Each
one reports severity counts, escalations fired, busiest paths, anomalies, and a
**policy self-check** that escalations equaled the Error count (nothing below
Warning escalated).

## Action-level provenance

Every read and write goes through the sanctioned wrappers in
[`compsuite/provenance.py`](./compsuite/provenance.py) and is appended to a
daily NDJSON ledger: `logs/provenance/provenance-YYYY-MM-DD.ndjson`. Each line
records `action_id`, `parent_run_id`, `seq`, `ts`, `verb`
(`READ/WRITE/CLASSIFY/ESCALATE/REFLECT/SCAN`), `target`, `severity`, `sha256`,
`bytes`, and `detail`.

Because every IO record carries the SHA-256 of the bytes touched, you can
re-hash a file later and confirm it matches what the ledger claims
(`provenance.verify_record`). That gives you a tamper-evident, fully traceable
chain of who/what touched which bytes when.

### Inspect the ledger

```bash
# pretty-print today's provenance actions
python -c "import json,sys; [print(json.dumps(json.loads(l),indent=2)) for l in open(sys.argv[1])]" \
  logs/provenance/provenance-$(date -u +%F).ndjson

# count actions by verb
cut -f1 -d',' logs/provenance/provenance-*.ndjson >/dev/null  # (NDJSON is JSON per line; use jq if available:)
# jq -r .verb logs/provenance/provenance-*.ndjson | sort | uniq -c
```

## Layout

```
compsuite.py          # entry point / CLI (run, scan, config, selftest)
compsuite/
  provenance.py       # action ids + the ONLY sanctioned IO path + ledger
  classifier.py       # event -> Normal/Warning/Error (+ severity ordering)
  escalation.py       # the single escalation gate + sinks
  reflection.py       # periodic reflection summaries
  watcher.py          # the watch loop over the two roots
config/compsuite.toml # watched roots, classification rules, thresholds
AGENTS.md             # the operating contract (read this)
```

## Running as a service

CompSuite is a plain long-running process. Wrap `python compsuite.py run` in
your supervisor of choice — `systemd`, `launchd`, `supervisord`, a container
restart policy, etc. It re-reads its checkpoint on start, so restarts are safe.
