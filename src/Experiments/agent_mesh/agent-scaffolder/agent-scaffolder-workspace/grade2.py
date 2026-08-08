#!/usr/bin/env python3
"""Grade iteration-2 fresh runs, carry forward iteration-1 baselines for evals 0-2,
and assemble the eval-<id>-<name>/<config>/run-1/ layout under iteration-2/runs/."""
import json, re, shutil
from pathlib import Path

WS = Path("/sessions/busy-vibrant-tesla/mnt/outputs/agent-scaffolder-workspace")
I1 = WS / "iteration-1"
I2 = WS / "iteration-2"
RAW = I2 / "raw"
RUNS = I2 / "runs"

EVALS = [
    {"id": 0, "name": "refactorbot-folder-scaffold",
     "prompt": "I'm starting a new folder for a CLI refactor bot called RefactorBot. It should only output raw diffs, never use a casual tone, and explain performance gains per line. Set it up for me."},
    {"id": 1, "name": "finlit-system-prompt",
     "prompt": "Write me a system prompt for a FinLit planner agent. It should be friendly, help users build budgets, but it must not give specific investment buy/sell advice."},
    {"id": 2, "name": "multiagent-agents-md-atp",
     "prompt": "Set up an AGENTS.md for a multi-agent docs project where a Writer agent and a Reviewer agent need to coordinate with each other."},
    {"id": 3, "name": "audit-agent-provenance",
     "prompt": "Set up an audit agent called CompSuite. It watches my voice_logs/ and outputs/ directories, classifies each file event as Normal / Warning / Error, and must only escalate above Warning. It runs unattended and writes daily logs, and I want a reflection summary every 50 actions or so. I also want full action-level provenance tracking so every read/write is traceable."},
]

# fresh runs in iteration-2 and their captured timing
FRESH = {
    ("refactorbot-folder-scaffold", "with_skill"):   {"total_tokens": 37624, "duration_ms": 88991},
    ("finlit-system-prompt", "with_skill"):          {"total_tokens": 41273, "duration_ms": 119945},
    ("multiagent-agents-md-atp", "with_skill"):      {"total_tokens": 51576, "duration_ms": 190763},
    ("audit-agent-provenance", "with_skill"):        {"total_tokens": 39633, "duration_ms": 110293},
    ("audit-agent-provenance", "without_skill"):     {"total_tokens": 80749, "duration_ms": 463784},
}

def gather(outputs: Path):
    paths, texts = [], []
    for f in sorted(outputs.rglob("*")):
        if f.is_file():
            paths.append(str(f.relative_to(outputs)))
            if f.suffix.lower() in {".pyc",".png",".jpg",".jpeg",".gif",".webp"}:
                continue
            try: texts.append(f.read_text(errors="replace"))
            except OSError: pass
    return paths, "\n".join(texts).lower()

def has_file(paths, b): return any(Path(p).name.lower()==b.lower() for p in paths)
def has_path(paths, n): return any(n.lower() in p.lower() for p in paths)
def E(text, ok, ev): return {"text": text, "passed": bool(ok), "evidence": ev}

def grade(eid, paths, t):
    e=[]
    if eid==0:
        e.append(E("Creates an AGENTS.md file", has_file(paths,"AGENTS.md"), f"files: {paths}"))
        e.append(E("Creates an index.md folder-context file", has_file(paths,"index.md"), f"files: {paths}"))
        e.append(E("Creates a .codex/instructions.md behavior file", has_path(paths,".codex") and has_file(paths,"instructions.md"), f"files: {paths}"))
        e.append(E("Agent Card uses the Role / Mission / Output Standards / Escalation layers", all(k in t for k in ["role","mission","output standard","escalation"]), "searched output text"))
        e.append(E("Encodes the raw-diffs-only output rule", "diff" in t and ("raw" in t or "only" in t or "unified" in t), "looked for diff + raw/only/unified"))
        e.append(E("Encodes the non-casual / formal tone rule", "casual" in t or "formal" in t, "looked for casual/formal"))
        e.append(E("Encodes the per-line performance-gain rule", "performance" in t and bool(re.search(r"per[ -](line|hunk|change)", t)), "performance + per line/hunk/change"))
    elif eid==1:
        e.append(E("Produces a system-prompt / Agent Card markdown file", any(p.lower().endswith(".md") for p in paths), f"files: {paths}"))
        e.append(E("Includes a Role layer", "role" in t, "searched output text"))
        e.append(E("Includes a Mission layer", "mission" in t, "searched output text"))
        e.append(E("Includes an Output Standards layer", "output standard" in t, "searched output text"))
        e.append(E("Includes an Escalation Rules layer", "escalation" in t, "searched output text"))
        e.append(E("Explicitly prohibits specific investment buy/sell advice", ("invest" in t) and bool(re.search(r"\b(not|no|never|avoid|don't|cannot|can't|must not|won't|refrain|prohibit)\b", t)), "invest + negation"))
        e.append(E("Specifies a friendly / warm tone", any(w in t for w in ["friendly","warm","encouraging","supportive"]), "friendly/warm/encouraging/supportive"))
    elif eid==2:
        e.append(E("Produces an AGENTS.md file", has_file(paths,"AGENTS.md"), f"files: {paths}"))
        e.append(E("Defines a Writer agent", "writer" in t, "searched output text"))
        e.append(E("Defines a Reviewer agent", "reviewer" in t, "searched output text"))
        e.append(E("Uses the Agent Card formula (Role + Mission)", "role" in t and "mission" in t, "searched output text"))
        e.append(E("References the ATP / artemis-transmission-protocol communication layer", ("atp" in t) or ("artemis" in t) or ("transmission protocol" in t), "atp/artemis/transmission protocol"))
    elif eid==3:
        e.append(E("Produces an AGENTS.md / audit agent card", has_file(paths,"AGENTS.md") or ("agent card" in t), f"files: {paths}"))
        e.append(E("Encodes observe-and-log-only boundaries (never modifies watched files)", bool(re.search(r"(do not|don't|never|only).{0,30}(modify|edit|delete|mutat)", t)) or "observe and log" in t or "read-only" in t or "read only" in t, "observe/log-only or no-modify rule"))
        e.append(E("Sets an escalation threshold above Warning", "escalat" in t and "warning" in t, "escalat + warning"))
        e.append(E("Declares file-based persistence with daily logs", "log" in t and ("daily" in t or ".log" in t or "logs/" in t or "log file" in t), "log + daily/.log/logs"))
        e.append(E("Specifies a reflection cadence (~50 actions / 12h)", ("reflect" in t or "summary" in t) and bool(re.search(r"\b(50|every|hour|action)", t)), "reflect/summary + cadence token"))
        e.append(E("References the atp-provenance-logging skill (parent/child prov_ids in agent_logs)", ("atp-provenance-logging" in t) or ("agent_logs" in t) or ("parent_prov_id" in t), "skill-specific provenance terms"))
    return e

def write_run(eid, name, config, src_outputs, timing_data):
    paths, t = gather(src_outputs)
    exps = grade(eid, paths, t)
    passed = sum(1 for x in exps if x["passed"]); total=len(exps)
    grading={"expectations":exps,"summary":{"passed":passed,"failed":total-passed,"total":total,"pass_rate":round(passed/total,4) if total else 0.0}}
    timing={"total_tokens":timing_data["total_tokens"],"duration_ms":timing_data["duration_ms"],"total_duration_seconds":round(timing_data["duration_ms"]/1000,1)}
    meta={"eval_id":eid,"eval_name":name,"prompt":next(e["prompt"] for e in EVALS if e["id"]==eid),"assertions":[x["text"] for x in exps]}
    rd = RUNS / f"eval-{eid}-{name}" / config / "run-1"
    (rd/"outputs").mkdir(parents=True, exist_ok=True)
    for item in src_outputs.iterdir():
        dst = rd/"outputs"/item.name
        if item.is_dir(): shutil.copytree(item, dst, dirs_exist_ok=True)
        else: shutil.copy2(item, dst)
    (rd/"grading.json").write_text(json.dumps(grading,indent=2))
    (rd/"timing.json").write_text(json.dumps(timing,indent=2))
    (rd/"eval_metadata.json").write_text(json.dumps(meta,indent=2))
    print(f"eval-{eid} {config}: {passed}/{total}")

# 1) grade fresh runs
for (name, config), tm in FRESH.items():
    eid = next(e["id"] for e in EVALS if e["name"]==name)
    src = RAW / name / config / "outputs"
    if not src.is_dir():
        print(f"MISSING raw: {src}"); continue
    write_run(eid, name, config, src, tm)

# 2) carry forward iteration-1 baselines for evals 0,1,2
for ev in EVALS[:3]:
    src = I1/"runs"/f"eval-{ev['id']}-{ev['name']}"/"without_skill"/"run-1"
    dst = RUNS/f"eval-{ev['id']}-{ev['name']}"/"without_skill"/"run-1"
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print(f"carried baseline eval-{ev['id']} without_skill from iteration-1")
    else:
        print(f"MISSING iter1 baseline: {src}")
print("iteration-2 assembled")
