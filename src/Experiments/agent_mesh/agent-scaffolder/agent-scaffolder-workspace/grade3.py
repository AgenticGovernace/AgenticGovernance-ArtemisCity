#!/usr/bin/env python3
"""Grade iteration-3 fresh runs, carry iteration-2 baselines for evals 0-3, assemble
eval-<id>-<name>/<config>/run-1/ under iteration-3/runs/."""

import json
import re
import shutil
from pathlib import Path

WS = Path("/sessions/busy-vibrant-tesla/mnt/outputs/agent-scaffolder-workspace")
I2, I3 = WS / "iteration-2", WS / "iteration-3"
RAW, RUNS = I3 / "raw", I3 / "runs"

EVALS = [
    {
        "id": 0,
        "name": "refactorbot-folder-scaffold",
        "prompt": "I'm starting a new folder for a CLI refactor bot called RefactorBot. It should only output raw diffs, never use a casual tone, and explain performance gains per line. Set it up for me.",
    },
    {
        "id": 1,
        "name": "finlit-system-prompt",
        "prompt": "Write me a system prompt for a FinLit planner agent. It should be friendly, help users build budgets, but it must not give specific investment buy/sell advice.",
    },
    {
        "id": 2,
        "name": "multiagent-agents-md-atp",
        "prompt": "Set up an AGENTS.md for a multi-agent docs project where a Writer agent and a Reviewer agent need to coordinate with each other.",
    },
    {
        "id": 3,
        "name": "audit-agent-provenance",
        "prompt": "Set up an audit agent called CompSuite. It watches my voice_logs/ and outputs/ directories, classifies each file event as Normal / Warning / Error, and must only escalate above Warning. It runs unattended and writes daily logs, and I want a reflection summary every 50 actions or so. I also want full action-level provenance tracking so every read/write is traceable.",
    },
    {
        "id": 4,
        "name": "relay-integration-stack",
        "prompt": "Set up an agent called Relay that hands off tasks to other agents over our ATP protocol, persists its reflections to its own Notion page so they survive across sessions, and logs every action for audit. It runs as part of our ramble stack.",
    },
]

FRESH = {
    ("refactorbot-folder-scaffold", "with_skill"): {
        "total_tokens": 44311,
        "duration_ms": 125263,
    },
    ("finlit-system-prompt", "with_skill"): {
        "total_tokens": 44504,
        "duration_ms": 218057,
    },
    ("multiagent-agents-md-atp", "with_skill"): {
        "total_tokens": 54167,
        "duration_ms": 200197,
    },
    ("audit-agent-provenance", "with_skill"): {
        "total_tokens": 49856,
        "duration_ms": 192977,
    },
    ("relay-integration-stack", "with_skill"): {
        "total_tokens": 59231,
        "duration_ms": 255661,
    },
    ("relay-integration-stack", "without_skill"): {
        "total_tokens": 86251,
        "duration_ms": 612880,
    },
}


def gather(o):
    paths, texts = [], []
    for f in sorted(o.rglob("*")):
        if f.is_file():
            paths.append(str(f.relative_to(o)))
            if f.suffix.lower() in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                continue
            try:
                texts.append(f.read_text(errors="replace"))
            except OSError:
                pass
    return paths, "\n".join(texts).lower()


def hf(p, b):
    return any(Path(x).name.lower() == b.lower() for x in p)


def hp(p, n):
    return any(n.lower() in x.lower() for x in p)


def E(t, ok, ev):
    return {"text": t, "passed": bool(ok), "evidence": ev}


def grade(eid, p, t):
    e = []
    if eid == 0:
        e += [
            E("Creates an AGENTS.md file", hf(p, "AGENTS.md"), f"{p}"),
            E("Creates an index.md folder-context file", hf(p, "index.md"), f"{p}"),
            E(
                "Creates a .codex/instructions.md behavior file",
                hp(p, ".codex") and hf(p, "instructions.md"),
                f"{p}",
            ),
            E(
                "Agent Card uses Role / Mission / Output Standards / Escalation layers",
                all(
                    k in t for k in ["role", "mission", "output standard", "escalation"]
                ),
                "text",
            ),
            E(
                "Encodes the raw-diffs-only output rule",
                "diff" in t and ("raw" in t or "only" in t or "unified" in t),
                "text",
            ),
            E(
                "Encodes the non-casual / formal tone rule",
                "casual" in t or "formal" in t,
                "text",
            ),
            E(
                "Encodes the per-line performance-gain rule",
                "performance" in t and bool(re.search(r"per[ -](line|hunk|change)", t)),
                "text",
            ),
        ]
    elif eid == 1:
        e += [
            E(
                "Produces a system-prompt / Agent Card markdown file",
                any(x.lower().endswith(".md") for x in p),
                f"{p}",
            ),
            E("Includes a Role layer", "role" in t, "text"),
            E("Includes a Mission layer", "mission" in t, "text"),
            E("Includes an Output Standards layer", "output standard" in t, "text"),
            E("Includes an Escalation Rules layer", "escalation" in t, "text"),
            E(
                "Explicitly prohibits specific investment buy/sell advice",
                ("invest" in t)
                and bool(
                    re.search(
                        r"\b(not|no|never|avoid|don't|cannot|can't|must not|won't|refrain|prohibit)\b",
                        t,
                    )
                ),
                "text",
            ),
            E(
                "Specifies a friendly / warm tone",
                any(w in t for w in ["friendly", "warm", "encouraging", "supportive"]),
                "text",
            ),
        ]
    elif eid == 2:
        e += [
            E("Produces an AGENTS.md file", hf(p, "AGENTS.md"), f"{p}"),
            E("Defines a Writer agent", "writer" in t, "text"),
            E("Defines a Reviewer agent", "reviewer" in t, "text"),
            E(
                "Uses the Agent Card formula (Role + Mission)",
                "role" in t and "mission" in t,
                "text",
            ),
            E(
                "References the ATP / artemis-transmission-protocol layer",
                ("atp" in t) or ("artemis" in t) or ("transmission protocol" in t),
                "text",
            ),
        ]
    elif eid == 3:
        e += [
            E(
                "Produces an AGENTS.md / audit agent card",
                hf(p, "AGENTS.md") or ("agent card" in t),
                f"{p}",
            ),
            E(
                "Encodes observe-and-log-only boundaries",
                bool(
                    re.search(
                        r"(do not|don't|never|only).{0,30}(modify|edit|delete|mutat)", t
                    )
                )
                or "observe and log" in t
                or "read-only" in t
                or "read only" in t,
                "text",
            ),
            E(
                "Sets an escalation threshold above Warning",
                "escalat" in t and "warning" in t,
                "text",
            ),
            E(
                "Declares file-based persistence with daily logs",
                "log" in t
                and ("daily" in t or ".log" in t or "logs/" in t or "log file" in t),
                "text",
            ),
            E(
                "Specifies a reflection cadence (~50 actions / 12h)",
                ("reflect" in t or "summary" in t)
                and bool(re.search(r"\b(50|every|hour|action)", t)),
                "text",
            ),
            E(
                "References the atp-provenance-logging skill",
                ("atp-provenance-logging" in t)
                or ("agent_logs" in t)
                or ("parent_prov_id" in t),
                "text",
            ),
        ]
    elif eid == 4:
        e += [
            E(
                "Produces an AGENTS.md / agent card",
                hf(p, "AGENTS.md") or ("agent card" in t),
                f"{p}",
            ),
            E(
                "References ATP / artemis-transmission-protocol for comms",
                ("atp" in t) or ("artemis" in t) or ("transmission protocol" in t),
                "text",
            ),
            E(
                "Notion-backed memory & reflection",
                "notion" in t and ("reflect" in t or "memory" in t),
                "text",
            ),
            E(
                "References the atp-provenance-logging skill for audit",
                ("atp-provenance-logging" in t)
                or ("agent_logs" in t)
                or ("parent_prov_id" in t),
                "text",
            ),
            E(
                "States the persistence tier / where reflections persist",
                ("persistence" in t and ("tier" in t or "external" in t))
                or ("notion page" in t),
                "text",
            ),
            E(
                "Routes through the ramble server (tier-1 MCP)",
                ("3748" in t)
                or ("ramble.kb" in t)
                or ("kb_write" in t)
                or ("ramble server" in t),
                "text",
            ),
        ]
    return e


def write_run(eid, name, config, src, tm):
    p, t = gather(src)
    exps = grade(eid, p, t)
    pa = sum(1 for x in exps if x["passed"])
    tot = len(exps)
    g = {
        "expectations": exps,
        "summary": {
            "passed": pa,
            "failed": tot - pa,
            "total": tot,
            "pass_rate": round(pa / tot, 4) if tot else 0.0,
        },
    }
    tim = {
        "total_tokens": tm["total_tokens"],
        "duration_ms": tm["duration_ms"],
        "total_duration_seconds": round(tm["duration_ms"] / 1000, 1),
    }
    meta = {
        "eval_id": eid,
        "eval_name": name,
        "prompt": next(x["prompt"] for x in EVALS if x["id"] == eid),
        "assertions": [x["text"] for x in exps],
    }
    rd = RUNS / f"eval-{eid}-{name}" / config / "run-1"
    (rd / "outputs").mkdir(parents=True, exist_ok=True)
    for it in src.iterdir():
        d = rd / "outputs" / it.name
        if it.is_dir():
            shutil.copytree(it, d, dirs_exist_ok=True)
        else:
            shutil.copy2(it, d)
    (rd / "grading.json").write_text(json.dumps(g, indent=2))
    (rd / "timing.json").write_text(json.dumps(tim, indent=2))
    (rd / "eval_metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"eval-{eid} {config}: {pa}/{tot}")


for (name, config), tm in FRESH.items():
    eid = next(x["id"] for x in EVALS if x["name"] == name)
    src = RAW / name / config / "outputs"
    if not src.is_dir():
        print(f"MISSING raw {src}")
        continue
    write_run(eid, name, config, src, tm)

for ev in EVALS[:4]:
    s = I2 / "runs" / f"eval-{ev['id']}-{ev['name']}" / "without_skill" / "run-1"
    d = RUNS / f"eval-{ev['id']}-{ev['name']}" / "without_skill" / "run-1"
    if s.is_dir():
        shutil.copytree(s, d, dirs_exist_ok=True)
        print(f"carried baseline eval-{ev['id']}")
    else:
        print(f"MISSING iter2 baseline {s}")
print("iteration-3 assembled")
