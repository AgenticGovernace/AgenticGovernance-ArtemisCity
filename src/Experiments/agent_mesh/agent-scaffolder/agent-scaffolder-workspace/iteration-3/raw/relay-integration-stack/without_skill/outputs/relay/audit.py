"""audit.py — append-only audit logger for Relay.

Every action Relay takes is logged here BEFORE it counts as done. The log is
append-only (one JSON object per line). If a write fails and `halt_on_log_failure`
is set, we raise AuditHaltError so the caller halts the action instead of acting
silently. No silent actions, ever.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone


class AuditHaltError(RuntimeError):
    """Raised when the audit log cannot be written and the action must halt."""


VALID_ACTIONS = {
    "task_read",
    "notion_read",
    "route_decision",
    "atp_send",
    "ack_received",
    "reroute",
    "timeout",
    "notion_write",
    "reflection",
    "escalation",
    "fault",
    "session_start",
    "session_end",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_prov_id() -> str:
    """Per-action provenance id."""
    return "prv_" + secrets.token_hex(2)


class AuditLog:
    """Append-only JSONL audit trail."""

    def __init__(self, path: str, session_id: str, halt_on_failure: bool = True):
        self.path = path
        self.session_id = session_id
        self.halt_on_failure = halt_on_failure
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def log(
        self,
        action: str,
        outcome: str = "ok",
        ctx: str | None = None,
        target: str | None = None,
        detail: str = "",
        prov_id: str | None = None,
    ) -> str:
        """Append one audit record. Returns the prov_id.

        Raises AuditHaltError if the write fails and halt_on_failure is True.
        """
        if action not in VALID_ACTIONS:
            # An unknown action type is itself a fault we must not hide.
            action = "fault"
            detail = f"[unknown action] {detail}"

        prov_id = prov_id or new_prov_id()
        record = {
            "ts": _utc_now(),
            "session_id": self.session_id,
            "actor": "Relay",
            "action": action,
            "ctx": ctx,
            "target": target,
            "detail": detail,
            "outcome": outcome,
            "prov_id": prov_id,
        }
        line = json.dumps(record, ensure_ascii=False)
        try:
            # Append-only: open in 'a', flush + fsync so the record is durable
            # before the action is considered logged.
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            if self.halt_on_failure:
                raise AuditHaltError(
                    f"Audit log unwritable ({self.path}): {exc}. Halting action."
                ) from exc
            # If halting is disabled we still surface the failure loudly.
            raise
        return prov_id
