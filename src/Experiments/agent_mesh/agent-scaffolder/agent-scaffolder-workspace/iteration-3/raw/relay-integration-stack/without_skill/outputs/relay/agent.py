"""agent.py — Relay, the ramble-stack task-handoff dispatcher.

Reference runtime that wires together the three guarantees from AGENTS.md:

  1. Handoff over ATP   -> atp.py     (build/parse transmissions, ack matching)
  2. Persistent memory  -> memory.py  (reflections to Notion, mirror fallback)
  3. Full audit         -> audit.py   (append-only log, halt on write failure)

Relay routes; it does NOT execute delegated work. Every action is logged before it
counts as done. Reflections are persisted to Notion. Unknown ATP tags halt.

This is a single-cycle, file-based reference: a task comes in, Relay routes it, writes
the ATP block to handoffs/outbox/<ctx>.atp, and (if a matching reply already sits in
handoffs/inbox/) processes the ack. A real deployment would loop and poll the inbox.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import atp
from .audit import AuditHaltError, AuditLog
from .memory import ReflectionStore


def _repo_root() -> str:
    # agent.py lives in relay/; the stack root is its parent.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%MZ")
    return f"relay-{stamp}-{secrets.token_hex(2)}"


@dataclass
class Task:
    summary: str
    payload: str
    mode: str = "Build"
    action_type: str = "Execute"
    priority: str = "Normal"
    target_zone: str = ""
    special_notes: str = ""
    # Optional explicit hints; otherwise Relay infers from capability keywords.
    wanted_capabilities: Optional[List[str]] = None


class Relay:
    def __init__(self, root: Optional[str] = None):
        self.root = root or _repo_root()
        self.config = _load_json(os.path.join(self.root, "relay", "relay.config.json"))
        self.registry = _load_json(os.path.join(self.root, "relay", "registry.json"))
        self.session_id = _new_session_id()

        p = self.config["paths"]
        self.outbox = os.path.join(self.root, p["outbox"])
        self.inbox = os.path.join(self.root, p["inbox"])
        os.makedirs(self.outbox, exist_ok=True)
        os.makedirs(self.inbox, exist_ok=True)

        self.audit = AuditLog(
            path=os.path.join(self.root, p["audit_log"]),
            session_id=self.session_id,
            halt_on_failure=self.config["audit"].get("halt_on_log_failure", True),
        )
        self.memory = ReflectionStore(
            page_id=self.config["notion"]["reflections_page_id"],
            mirror_path=os.path.join(self.root, p["reflections_mirror"]),
            auth_env_var=self.config["notion"].get("auth_env_var", "NOTION_API_KEY"),
        )
        self.max_retries = int(self.config.get("max_handoff_retries", 2))

    # ---- session lifecycle -------------------------------------------------

    def start_session(self) -> List[str]:
        self.audit.log("session_start", detail=f"session={self.session_id}")
        prior = self.memory.load_reflections()
        self.audit.log(
            "notion_read",
            detail=f"loaded {len(prior)} prior reflection(s) from persistent memory",
        )
        return prior

    def end_session(self) -> None:
        self._reflect("Session ended; all handoffs logged and reflections persisted.")
        self.audit.log("session_end", detail=f"session={self.session_id}")

    # ---- routing -----------------------------------------------------------

    def route(self, task: Task) -> Optional[dict]:
        """Pick the best downstream agent. Returns the agent dict or None (escalate)."""
        wanted = set(task.wanted_capabilities or self._infer_capabilities(task))
        candidates = []
        for agent in self.registry["agents"]:
            caps = set(agent.get("capabilities", []))
            score = len(wanted & caps)
            mode_ok = task.mode in agent.get("accepts_modes", []) or not agent.get(
                "accepts_modes"
            )
            if score > 0 and mode_ok:
                candidates.append((score, -agent.get("load_hint", 1), agent))
        if not candidates:
            self.audit.log(
                "route_decision",
                outcome="halted",
                detail=f"no agent matches caps={sorted(wanted)} mode={task.mode}",
            )
            self._escalate(
                f"No downstream agent for task '{task.summary}' "
                f"(caps={sorted(wanted)}, mode={task.mode})."
            )
            return None
        candidates.sort(reverse=True)
        chosen = candidates[0][2]
        tie = len(candidates) > 1 and candidates[0][0] == candidates[1][0]
        note = " Assumption: tie broken by lower load_hint." if tie else ""
        self.audit.log(
            "route_decision",
            target=chosen["name"],
            detail=f"caps={sorted(wanted)} -> {chosen['name']}.{note}",
        )
        return chosen

    @staticmethod
    def _infer_capabilities(task: Task) -> List[str]:
        text = (task.summary + " " + task.payload).lower()
        vocab = [
            "draft",
            "document",
            "summarize",
            "write",
            "scaffold",
            "review",
            "verify",
            "lint",
            "code",
            "refactor",
            "execute",
            "build",
            "run",
            "organize",
            "tag",
            "file",
            "index",
        ]
        hits = [w for w in vocab if w in text]
        return hits or ["execute"]

    # ---- handoff -----------------------------------------------------------

    def hand_off(self, task: Task) -> dict:
        """Route + send an ATP handoff for one task. Returns a result dict."""
        agent = self.route(task)
        if agent is None:
            return {"status": "ESCALATED", "reason": "no_target_agent"}

        ctx = atp.new_ctx()
        tx = atp.Transmission(
            to=agent["atp_address"],
            ctx=ctx,
            mode=task.mode,
            context=task.summary,
            priority=task.priority,
            action_type=task.action_type,
            target_zone=task.target_zone,
            special_notes=task.special_notes,
            request_tag="==handoff==",
            expect="==accept==",
            payload=task.payload,
        )
        try:
            rendered = tx.render()
        except atp.ATPFault as exc:
            self.audit.log("fault", outcome="halted", ctx=ctx, detail=f"build: {exc}")
            self._reflect(f"Halted handoff for '{task.summary}': {exc}", ctx=ctx)
            return {"status": "HALTED", "reason": str(exc)}

        out_path = os.path.join(self.outbox, f"{ctx}.atp")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(rendered)
        self.audit.log(
            "atp_send",
            ctx=ctx,
            target=agent["name"],
            detail=f"handoff Mode={task.mode} ActionType={task.action_type} expect===accept==",
        )

        result = self._await_ack(tx, agent, task)
        self._reflect(
            f"Handed '{task.summary}' to {agent['name']}; outcome={result['status']}.",
            ctx=ctx,
        )
        return result

    def _await_ack(self, tx: atp.Transmission, agent: dict, task: Task) -> dict:
        """Look for a matching reply in the inbox. File-based; a live system polls."""
        reply_name = atp.reply_ctx_for(tx.ctx) + ".atp"
        reply_path = os.path.join(self.inbox, reply_name)
        if not os.path.exists(reply_path):
            # No ack present this cycle -> TIMEOUT path (retry/escalate handled by loop).
            self.audit.log(
                "timeout",
                ctx=tx.ctx,
                target=agent["name"],
                detail=f"no ack at {reply_name} within this cycle",
            )
            return {"status": "TIMEOUT", "ctx": tx.ctx, "target": agent["name"]}

        with open(reply_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        try:
            reply = atp.parse_reply(raw)
            ack = atp.match_ack(tx, reply)
        except atp.ATPFault as exc:
            # Fault-awareness layer: unknown tag / ctx mismatch -> halt + escalate.
            self.audit.log("fault", outcome="halted", ctx=tx.ctx, detail=str(exc))
            self._escalate(f"ATP fault on {tx.ctx}: {exc}")
            return {"status": "HALTED", "reason": str(exc), "ctx": tx.ctx}

        self.audit.log(
            "ack_received", ctx=tx.ctx, target=agent["name"], detail=f"ack={ack}"
        )
        if ack == "==accept==":
            return {"status": "IN_PROGRESS", "ctx": tx.ctx, "target": agent["name"]}
        if ack == "==decline==":
            self.audit.log(
                "reroute", ctx=tx.ctx, target=agent["name"], detail="declined"
            )
            return {"status": "REROUTE", "ctx": tx.ctx, "declined_by": agent["name"]}
        return {"status": "IN_PROGRESS", "ctx": tx.ctx, "ack": ack}

    # ---- memory + escalation ----------------------------------------------

    def _reflect(self, text: str, ctx: Optional[str] = None) -> None:
        sink, ok = self.memory.add_reflection(text, self.session_id, ctx=ctx)
        self.audit.log(
            "reflection",
            ctx=ctx,
            outcome="ok" if ok else "error",
            detail=f"persisted to {sink}: {text}",
        )
        if not ok:
            self.audit.log(
                "fault",
                ctx=ctx,
                outcome="error",
                detail="notion_unreachable: reflection written to local mirror, reconcile next session",
            )

    def _escalate(self, reason: str) -> None:
        self.audit.log("escalation", outcome="halted", detail=reason)
        self._reflect(f"Escalated to human: {reason}")


def main(argv: Optional[List[str]] = None) -> int:
    """Demo run: start a session, hand off one sample task, end the session."""
    relay = Relay()
    try:
        relay.start_session()
        sample = Task(
            summary="Draft the v2 onboarding guide from the ramble notes",
            payload="Cover install, first run, and the ATP handoff flow. Keep one H1.",
            mode="Build",
            action_type="Scaffold",
            priority="High",
            target_zone="ramble-stack/docs/onboarding",
            special_notes="Source notes in the ramble inbox.",
        )
        result = relay.hand_off(sample)
        print(json.dumps(result, indent=2))
        relay.end_session()
    except AuditHaltError as exc:
        # The one thing we never do is act without logging. If logging is impossible,
        # stop loudly.
        print(f"HALTED: {exc}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
