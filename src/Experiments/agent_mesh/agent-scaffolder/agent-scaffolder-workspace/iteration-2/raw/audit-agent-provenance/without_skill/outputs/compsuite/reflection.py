"""Periodic reflection summaries.

Roughly every N actions (default 50, from ``[reflection].every_n_actions``)
CompSuite writes a short markdown reflection over the window since the last one.
A reflection summarizes activity and runs a self-check that the escalation
policy held: *did I escalate exactly the Errors and nothing below Warning?*

Reflections never escalate; they are an observability/self-audit artifact.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .classifier import Severity
from .provenance import ProvenanceLedger


def _utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class ReflectionEngine:
    """Tracks a rolling window of activity and emits reflections.

    Call :meth:`note` once per classified event. When the number of actions
    since the last reflection reaches ``every_n_actions``, :meth:`note`
    triggers a reflection automatically. Call :meth:`flush` on shutdown.
    """

    ledger: ProvenanceLedger
    log_dir: Path
    every_n_actions: int = 50

    # rolling window state
    _seq: int = field(default=0, init=False)              # reflection counter
    _since_last: int = field(default=0, init=False)       # actions in window
    _severity_counts: Counter = field(default_factory=Counter, init=False)
    _path_counts: Counter = field(default_factory=Counter, init=False)
    _escalations: int = field(default=0, init=False)
    _window_started: str = field(default_factory=_utc_now_compact, init=False)

    def note(self, severity: Severity, path: str, escalated: bool) -> None:
        """Record one classified event into the current window.

        Emits a reflection automatically once the window fills.
        """
        self._since_last += 1
        self._severity_counts[severity.label] += 1
        self._path_counts[path] += 1
        if escalated:
            self._escalations += 1

        if self._since_last >= self.every_n_actions:
            self.emit(trigger="window_full")

    def emit(self, *, trigger: str = "manual") -> Path | None:
        """Write a reflection file for the current window and reset it.

        Returns the path written, or None if the window was empty.
        """
        if self._since_last == 0:
            return None

        self._seq += 1
        normal = self._severity_counts.get("Normal", 0)
        warning = self._severity_counts.get("Warning", 0)
        error = self._severity_counts.get("Error", 0)

        # Self-check: escalations must equal the number of Errors, since the
        # gate escalates iff rank > Warning (i.e., Error only).
        policy_ok = self._escalations == error
        policy_line = (
            "PASS — escalations match Error count; nothing below Warning escalated."
            if policy_ok
            else (
                f"FAIL — {self._escalations} escalations vs {error} Errors. "
                "Investigate: the escalation gate may have been bypassed."
            )
        )

        busiest = self._path_counts.most_common(5)
        busiest_md = (
            "\n".join(f"- `{p}` — {n} event(s)" for p, n in busiest)
            if busiest
            else "- (none)"
        )

        now = _utc_now_compact()
        body = f"""# CompSuite reflection #{self._seq}

- **Run:** `{self.ledger.parent_run_id}`
- **Window:** {self._window_started} → {now}
- **Trigger:** {trigger}
- **Actions in window:** {self._since_last}

## Severity breakdown

| Severity | Count |
|----------|-------|
| Normal   | {normal} |
| Warning  | {warning} |
| Error    | {error} |

## Escalations

- Fired this window: **{self._escalations}**
- Policy self-check: {policy_line}

## Busiest paths

{busiest_md}

## Notes

{self._anomaly_notes(normal, warning, error)}
"""

        out = Path(self.log_dir) / "reflections" / f"reflection-{self._seq:04d}-{now}.md"
        # Written through the ledger so the reflection write is itself traceable.
        self.ledger.write_file(out, body, detail=f"reflection#{self._seq}")
        self.ledger.record("REFLECT", str(out), detail=f"window={self._since_last}")

        # Reset the window.
        self._since_last = 0
        self._severity_counts.clear()
        self._path_counts.clear()
        self._escalations = 0
        self._window_started = now
        return out

    def flush(self) -> Path | None:
        """Emit a final reflection on shutdown (if the window is non-empty)."""
        return self.emit(trigger="shutdown")

    @staticmethod
    def _anomaly_notes(normal: int, warning: int, error: int) -> str:
        total = normal + warning + error
        if total == 0:
            return "No activity recorded."
        notes = []
        if error > 0:
            notes.append(f"- {error} Error(s) were escalated this window.")
        if warning and warning >= max(1, total // 2):
            notes.append(
                f"- Warning rate is high ({warning}/{total}). Possible misconfigured "
                "producer or unexpected file types entering the watched trees."
            )
        if not notes:
            notes.append("- Steady state; nothing notable.")
        return "\n".join(notes)
