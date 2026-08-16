"""The escalation gate — CompSuite's single most important rule.

> CompSuite must only escalate above Warning.

That rule is implemented in exactly one place, :func:`should_escalate`, so it
cannot be bypassed by accident. "Above Warning" means a severity whose rank is
strictly greater than Warning's — i.e., Error only. Normal and Warning never
escalate.

When an Error does fire, :class:`Escalator` routes it to the configured sinks
(log file by default; an optional operator command). Every escalation is itself
recorded in the provenance ledger as an ESCALATE action.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .classifier import Severity
from .provenance import ProvenanceLedger


def should_escalate(severity: Severity, threshold: Severity = Severity.WARNING) -> bool:
    """Return True iff ``severity`` ranks strictly above ``threshold``.

    This is THE gate. With the default threshold (Warning), only Error escalates.
    There is intentionally no other code path that triggers an escalation.
    """
    return int(severity) > int(threshold)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Escalator:
    """Routes escalations to sinks, gated by :func:`should_escalate`.

    Parameters
    ----------
    ledger:
        Provenance ledger; escalations are written through it (sanctioned IO)
        and recorded as ESCALATE actions.
    log_dir:
        Where ``escalations.log`` lives.
    threshold:
        Severity threshold; escalate strictly above it. Default Warning.
    sinks:
        Iterable of sink names: "log" and/or "command".
    command:
        Shell command template for the "command" sink, with ``{severity}``,
        ``{path}`` and ``{detail}`` placeholders. Empty disables it.
    """

    ledger: ProvenanceLedger
    log_dir: Path
    threshold: Severity = Severity.WARNING
    sinks: tuple[str, ...] = ("log",)
    command: str = ""

    escalation_count: int = field(default=0, init=False)

    def maybe_escalate(self, severity: Severity, path: str, detail: str) -> bool:
        """Escalate ``(severity, path, detail)`` iff the gate allows it.

        Returns True if an escalation fired, False otherwise. Safe to call for
        every event — Normal/Warning are simply no-ops.
        """
        if not should_escalate(severity, self.threshold):
            return False

        self.escalation_count += 1
        line = f"{_utc_now_iso()}\tESCALATION\t{severity.label}\t{path}\t{detail}\n"

        if "log" in self.sinks:
            # Sanctioned, hashed, traceable write.
            self.ledger.write_file(
                Path(self.log_dir) / "escalations.log",
                line,
                append=True,
                detail=f"escalation:{severity.label}",
            )

        if "command" in self.sinks and self.command:
            self._run_command(severity, path, detail)

        # Record the escalation as its own provenance action.
        self.ledger.record(
            "ESCALATE",
            path,
            severity=severity.label,
            detail=detail,
        )
        return True

    def _run_command(self, severity: Severity, path: str, detail: str) -> None:
        cmd = self.command.format(
            severity=shlex.quote(severity.label),
            path=shlex.quote(path),
            detail=shlex.quote(detail),
        )
        try:
            subprocess.run(cmd, shell=True, check=False, timeout=30)
        except Exception:  # pragma: no cover - sink must never crash the agent
            # An escalation sink failing must not take down the auditor; the
            # escalation is still recorded in the log + ledger above.
            pass

    @classmethod
    def from_config(
        cls,
        ledger: ProvenanceLedger,
        log_dir: Path,
        *,
        threshold_label: str = "Warning",
        sinks: Iterable[str] = ("log",),
        command: str = "",
    ) -> "Escalator":
        return cls(
            ledger=ledger,
            log_dir=Path(log_dir),
            threshold=Severity.from_label(threshold_label),
            sinks=tuple(sinks),
            command=command,
        )
