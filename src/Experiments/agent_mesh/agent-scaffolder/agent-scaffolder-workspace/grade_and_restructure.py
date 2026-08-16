#!/usr/bin/env python3
"""Grade iteration-1 runs against per-eval assertions and restructure the
workspace into the eval-<id>-<name>/<config>/run-1/ layout that both the
benchmark aggregator and the eval viewer understand."""

import json
import re
import shutil
from pathlib import Path

ITER = Path(
    "/sessions/busy-vibrant-tesla/mnt/outputs/agent-scaffolder-workspace/iteration-1"
)

# timing captured from the subagent task notifications
TIMING = {
    ("refactorbot-folder-scaffold", "with_skill"): {
        "total_tokens": 31582,
        "duration_ms": 75705,
    },
    ("refactorbot-folder-scaffold", "without_skill"): {
        "total_tokens": 36026,
        "duration_ms": 159327,
    },
    ("finlit-system-prompt", "with_skill"): {
        "total_tokens": 33844,
        "duration_ms": 90945,
    },
    ("finlit-system-prompt", "without_skill"): {
        "total_tokens": 25531,
        "duration_ms": 77394,
    },
    ("multiagent-agents-md-atp", "with_skill"): {
        "total_tokens": 33231,
        "duration_ms": 93609,
    },
    ("multiagent-agents-md-atp", "without_skill"): {
        "total_tokens": 34477,
        "duration_ms": 135810,
    },
}

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
]


def gather(outputs: Path):
    """Return (list of relative file paths, concatenated lowercased text)."""
    paths, texts = [], []
    for f in sorted(outputs.rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(outputs))
            paths.append(rel)
            if f.suffix.lower() in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                continue
            try:
                texts.append(f.read_text(errors="replace"))
            except OSError:
                pass
    return paths, "\n".join(texts).lower()


def has_file(paths, basename):
    return any(Path(p).name.lower() == basename.lower() for p in paths)


def has_path(paths, needle):
    return any(needle.lower() in p.lower() for p in paths)


def E(text, passed, evidence):
    return {"text": text, "passed": bool(passed), "evidence": evidence}


def grade(eval_id, paths, t):
    exp = []
    if eval_id == 0:
        exp.append(
            E(
                "Creates an AGENTS.md file",
                has_file(paths, "AGENTS.md"),
                f"files: {paths}",
            )
        )
        exp.append(
            E(
                "Creates an index.md folder-context file",
                has_file(paths, "index.md"),
                f"files: {paths}",
            )
        )
        exp.append(
            E(
                "Creates a .codex/instructions.md behavior file",
                has_path(paths, ".codex") and has_file(paths, "instructions.md"),
                f"files: {paths}",
            )
        )
        layers = all(
            k in t for k in ["role", "mission", "output standard", "escalation"]
        )
        exp.append(
            E(
                "Agent Card uses the Role / Mission / Output Standards / Escalation layers",
                layers,
                "searched concatenated output text for the four layer labels",
            )
        )
        diffs = "diff" in t and ("raw" in t or "only" in t or "unified" in t)
        exp.append(
            E(
                "Encodes the raw-diffs-only output rule",
                diffs,
                "looked for 'diff' plus 'raw'/'only'/'unified'",
            )
        )
        tone = "casual" in t or "formal" in t
        exp.append(
            E(
                "Encodes the non-casual / formal tone rule",
                tone,
                "looked for 'casual' or 'formal'",
            )
        )
        perf = "performance" in t and bool(re.search(r"per[ -](line|hunk|change)", t))
        exp.append(
            E(
                "Encodes the per-line performance-gain rule",
                perf,
                "looked for 'performance' plus 'per line/hunk/change'",
            )
        )
    elif eval_id == 1:
        exp.append(
            E(
                "Produces a system-prompt / Agent Card markdown file",
                any(p.lower().endswith(".md") for p in paths),
                f"files: {paths}",
            )
        )
        exp.append(E("Includes a Role layer", "role" in t, "searched output text"))
        exp.append(
            E("Includes a Mission layer", "mission" in t, "searched output text")
        )
        exp.append(
            E(
                "Includes an Output Standards layer",
                "output standard" in t,
                "searched output text",
            )
        )
        exp.append(
            E(
                "Includes an Escalation Rules layer",
                "escalation" in t,
                "searched output text",
            )
        )
        invest = ("invest" in t) and bool(
            re.search(
                r"\b(not|no|never|avoid|don't|cannot|can't|must not|won't|refrain|prohibit)\b",
                t,
            )
        )
        exp.append(
            E(
                "Explicitly prohibits specific investment buy/sell advice",
                invest,
                "looked for 'invest' plus a negation token",
            )
        )
        friendly = any(
            w in t for w in ["friendly", "warm", "encouraging", "supportive"]
        )
        exp.append(
            E(
                "Specifies a friendly / warm tone",
                friendly,
                "looked for friendly/warm/encouraging/supportive",
            )
        )
    elif eval_id == 2:
        exp.append(
            E(
                "Produces an AGENTS.md file",
                has_file(paths, "AGENTS.md"),
                f"files: {paths}",
            )
        )
        exp.append(E("Defines a Writer agent", "writer" in t, "searched output text"))
        exp.append(
            E("Defines a Reviewer agent", "reviewer" in t, "searched output text")
        )
        exp.append(
            E(
                "Uses the Agent Card formula (Role + Mission)",
                "role" in t and "mission" in t,
                "searched output text",
            )
        )
        atp = ("atp" in t) or ("artemis" in t) or ("transmission protocol" in t)
        exp.append(
            E(
                "References the ATP / artemis-transmission-protocol communication layer",
                atp,
                "looked for 'atp'/'artemis'/'transmission protocol'",
            )
        )
    return exp


for ev in EVALS:
    for config in ["with_skill", "without_skill"]:
        src_out = ITER / ev["name"] / config / "outputs"
        if not src_out.is_dir():
            print(f"MISSING: {src_out}")
            continue
        paths, t = gather(src_out)
        exps = grade(ev["id"], paths, t)
        passed = sum(1 for e in exps if e["passed"])
        total = len(exps)
        grading = {
            "expectations": exps,
            "summary": {
                "passed": passed,
                "failed": total - passed,
                "total": total,
                "pass_rate": round(passed / total, 4) if total else 0.0,
            },
        }
        tm = TIMING[(ev["name"], config)]
        timing = {
            "total_tokens": tm["total_tokens"],
            "duration_ms": tm["duration_ms"],
            "total_duration_seconds": round(tm["duration_ms"] / 1000, 1),
        }
        meta = {
            "eval_id": ev["id"],
            "eval_name": ev["name"],
            "prompt": ev["prompt"],
            "assertions": [e["text"] for e in exps],
        }

        run_dir = ITER / f"eval-{ev['id']}-{ev['name']}" / config / "run-1"
        (run_dir / "outputs").mkdir(parents=True, exist_ok=True)
        # copy outputs
        for item in src_out.iterdir():
            dst = run_dir / "outputs" / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
        (run_dir / "grading.json").write_text(json.dumps(grading, indent=2))
        (run_dir / "timing.json").write_text(json.dumps(timing, indent=2))
        (run_dir / "eval_metadata.json").write_text(json.dumps(meta, indent=2))
        print(f"eval-{ev['id']} {config}: {passed}/{total} pass")

# remove the old descriptive-name dirs (now superseded by eval-<id>-<name>)
for ev in EVALS:
    old = ITER / ev["name"]
    if old.is_dir():
        shutil.rmtree(old)
print("restructure complete")
