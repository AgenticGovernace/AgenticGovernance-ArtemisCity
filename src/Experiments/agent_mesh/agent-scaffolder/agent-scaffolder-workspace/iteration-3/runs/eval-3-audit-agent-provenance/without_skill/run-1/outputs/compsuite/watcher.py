"""The watch loop: observe the two roots and drive the audit pipeline.

Default backend is a dependency-free **poller** that snapshots the watched
trees and diffs successive snapshots into create / modify / delete events.
An optional ``watchdog`` backend can be enabled in config for OS-native events.

For each event the loop:

  1. classifies it (Normal / Warning / Error),
  2. writes an audit-log line for the day,
  3. asks the escalation gate to act (Error only),
  4. notes it for the reflection engine (which fires every ~50 actions),
  5. records provenance actions throughout (CLASSIFY/SCAN plus the IO done by
     the audit/escalation/reflection writes themselves).

CompSuite is read-only on watched data: it only ever *reads* watched files (to
hash/inspect them) and *writes* inside ``logs/``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .classifier import Classification, FileEvent, Severity, classify_safe
from .escalation import Escalator
from .provenance import ProvenanceLedger
from .reflection import ReflectionEngine


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class WatchConfig:
    """Resolved configuration passed to the watcher."""

    watch_roots: list[Path]
    poll_interval_seconds: float
    backend: str
    # classification rules (forwarded to classify_safe)
    voice_logs_allowed_ext: list[str]
    outputs_allowed_ext: list[str]
    forbidden_ext: list[str]
    warn_on_unknown_extension: bool
    warn_on_zero_byte: bool
    warn_on_delete: bool
    error_on_out_of_tree: bool
    error_on_classifier_failure: bool


@dataclass
class Watcher:
    """Owns the run loop and wires together the audit pipeline components."""

    config: WatchConfig
    ledger: ProvenanceLedger
    escalator: Escalator
    reflection: ReflectionEngine
    log_dir: Path

    _snapshot: dict[str, float] = field(default_factory=dict, init=False)
    _root_of: dict[str, Path] = field(default_factory=dict, init=False)
    _running: bool = field(default=False, init=False)

    # ----- audit logging ---------------------------------------------------

    def _audit_path(self) -> Path:
        # Daily audit log; rolls over automatically on the UTC date boundary.
        return Path(self.log_dir) / f"audit-{_utc_date()}.log"

    def _write_audit(self, event: FileEvent, result: Classification, escalated: bool) -> None:
        line = "\t".join(
            [
                _utc_now_iso(),
                result.severity.label,
                event.kind,
                str(event.path),
                "ESCALATED" if escalated else "-",
                result.reason,
            ]
        ) + "\n"
        # Sanctioned, hashed write — the audit log entry is itself provenance.
        self.ledger.write_file(self._audit_path(), line, append=True, detail="audit-entry")

    # ----- snapshot diffing (poll backend) ---------------------------------

    def _scan(self) -> dict[str, float]:
        """Return {abs_path: mtime} for every file under the watch roots."""
        snap: dict[str, float] = {}
        for root in self.config.watch_roots:
            root = Path(root)
            if not root.exists():
                continue
            for p in root.rglob("*"):
                if p.is_file():
                    ap = str(p.resolve())
                    try:
                        snap[ap] = p.stat().st_mtime
                    except OSError:
                        # Unreadable file: surface as an Error-level event below
                        # by recording mtime as NaN sentinel handled in diff.
                        snap[ap] = float("nan")
                    self._root_of[ap] = root.resolve()
        return snap

    def _diff(self, old: dict[str, float], new: dict[str, float]) -> list[FileEvent]:
        events: list[FileEvent] = []
        old_keys, new_keys = set(old), set(new)

        for ap in new_keys - old_keys:
            events.append(self._make_event(ap, "created"))
        for ap in old_keys - new_keys:
            events.append(self._make_event(ap, "deleted"))
        for ap in old_keys & new_keys:
            # NaN != NaN, so an unreadable file always shows as "modified".
            if old[ap] != new[ap]:
                events.append(self._make_event(ap, "modified"))
        return events

    def _make_event(self, abs_path: str, kind: str) -> FileEvent:
        p = Path(abs_path)
        size: Optional[int] = None
        if kind != "deleted":
            try:
                size = p.stat().st_size
            except OSError:
                size = None
        root = self._root_of.get(abs_path, p.parent.resolve())
        return FileEvent(path=p, kind=kind, root=root, size=size)

    # ----- per-event pipeline ----------------------------------------------

    def process_event(self, event: FileEvent) -> Classification:
        """Classify one event, log it, escalate if warranted, and reflect."""
        result = classify_safe(
            event,
            error_on_failure=self.config.error_on_classifier_failure,
            watch_roots=self.config.watch_roots,
            voice_logs_allowed_ext=self.config.voice_logs_allowed_ext,
            outputs_allowed_ext=self.config.outputs_allowed_ext,
            forbidden_ext=self.config.forbidden_ext,
            warn_on_unknown_extension=self.config.warn_on_unknown_extension,
            warn_on_zero_byte=self.config.warn_on_zero_byte,
            warn_on_delete=self.config.warn_on_delete,
            error_on_out_of_tree=self.config.error_on_out_of_tree,
        )

        # Record the classification decision as a provenance action.
        self.ledger.record(
            "CLASSIFY",
            str(event.path),
            severity=result.severity.label,
            detail=result.reason,
        )

        # Escalation gate: acts on Error only (rank > Warning).
        escalated = self.escalator.maybe_escalate(
            result.severity, str(event.path), result.reason
        )

        # Audit log line.
        self._write_audit(event, result, escalated)

        # Feed the reflection engine (fires every ~N actions).
        self.reflection.note(result.severity, str(event.path), escalated)

        return result

    # ----- run loop ---------------------------------------------------------

    def run_once(self) -> list[Classification]:
        """Single scan/diff/process cycle. Returns the classifications made."""
        self.ledger.record("SCAN", ",".join(str(r) for r in self.config.watch_roots))
        new_snap = self._scan()
        events = self._diff(self._snapshot, new_snap)
        results = [self.process_event(ev) for ev in events]
        self._snapshot = new_snap
        self.ledger.checkpoint({"watched": len(new_snap)})
        return results

    def run_forever(self, *, max_cycles: Optional[int] = None) -> None:
        """Run unattended until stopped (or ``max_cycles`` cycles elapse).

        ``max_cycles`` is mainly for tests / bounded runs; leave None for a
        true daemon. Handles its own clean-shutdown reflection.
        """
        self._running = True
        # Seed the baseline snapshot so the first cycle doesn't report every
        # pre-existing file as "created".
        self._snapshot = self._scan()
        cycles = 0
        try:
            while self._running:
                time.sleep(self.config.poll_interval_seconds)
                self.run_once()
                cycles += 1
                if max_cycles is not None and cycles >= max_cycles:
                    break
        except KeyboardInterrupt:  # pragma: no cover - operator Ctrl-C
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the loop and emit a final reflection + checkpoint."""
        self._running = False
        self.reflection.flush()
        self.ledger.checkpoint({"stopped": _utc_now_iso()})
