"""Action-level provenance: the only sanctioned IO path in CompSuite.

Every read and every write CompSuite performs MUST go through this module so
that it is traceable. The contract (see AGENTS.md §7):

  * Each action gets a unique ``action_id`` (UUID4).
  * Each action is linked to its run via ``parent_run_id`` and ordered by a
    monotonic ``seq``.
  * IO actions carry the ``sha256`` and ``bytes`` of the data touched, making
    the log tamper-evident: you can re-hash a file and confirm it matches the
    bytes the ledger claims were read/written.

``ProvenanceLedger`` owns the run id, the sequence counter, and the append-only
NDJSON ledger file. ``read_file`` and ``write_file`` are the *only* functions
the rest of the agent should use to touch disk for watched data and logs.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


# Allowed action verbs. Kept explicit so an unknown verb is caught early.
VERBS = frozenset({"READ", "WRITE", "CLASSIFY", "ESCALATE", "REFLECT", "SCAN"})


@dataclass
class ActionRecord:
    """One provenance entry. Serialized as a single NDJSON line."""

    action_id: str
    parent_run_id: str
    seq: int
    ts: str
    verb: str
    target: str
    severity: Optional[str] = None
    sha256: Optional[str] = None
    bytes: Optional[int] = None
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


@dataclass
class ProvenanceLedger:
    """Owns the run identity and the append-only action ledger.

    Parameters
    ----------
    log_dir:
        Directory under which ``provenance/`` and ``.state.json`` live.
    parent_run_id:
        Stable id for this run/session. Generated if not supplied.
    flush_each_record:
        fsync-style flush after each write for crash safety.
    """

    log_dir: Path
    parent_run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    flush_each_record: bool = True

    # internal
    _seq: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.log_dir = Path(self.log_dir)
        (self.log_dir / "provenance").mkdir(parents=True, exist_ok=True)

    # ----- ledger plumbing -------------------------------------------------

    def _ledger_path(self) -> Path:
        # Daily provenance file, matching the daily audit log cadence.
        return self.log_dir / "provenance" / f"provenance-{_utc_date()}.ndjson"

    def _next_seq(self) -> int:
        # Caller must hold the lock.
        self._seq += 1
        return self._seq

    @property
    def action_count(self) -> int:
        """Number of actions recorded by this run so far."""
        return self._seq

    def record(
        self,
        verb: str,
        target: str,
        *,
        severity: Optional[str] = None,
        sha256: Optional[str] = None,
        num_bytes: Optional[int] = None,
        detail: str = "",
    ) -> ActionRecord:
        """Append one action to the ledger and return the record.

        This is the single chokepoint through which provenance is written.
        """
        if verb not in VERBS:
            raise ValueError(f"unknown provenance verb: {verb!r}")

        with self._lock:
            rec = ActionRecord(
                action_id=str(uuid.uuid4()),
                parent_run_id=self.parent_run_id,
                seq=self._next_seq(),
                ts=_utc_now_iso(),
                verb=verb,
                target=str(target),
                severity=severity,
                sha256=sha256,
                bytes=num_bytes,
                detail=detail,
            )
            path = self._ledger_path()
            with path.open("a", encoding="utf-8") as fh:
                fh.write(rec.to_json() + "\n")
                if self.flush_each_record:
                    fh.flush()
                    os.fsync(fh.fileno())
            return rec

    # ----- sanctioned IO ---------------------------------------------------

    def read_file(self, path: os.PathLike | str, *, detail: str = "") -> bytes:
        """Read a file and record a READ action with its content hash.

        This is the ONLY sanctioned way for CompSuite to read watched data.
        """
        p = Path(path)
        data = p.read_bytes()
        self.record(
            "READ",
            str(p.resolve()),
            sha256=sha256_bytes(data),
            num_bytes=len(data),
            detail=detail,
        )
        return data

    def write_file(
        self,
        path: os.PathLike | str,
        data: bytes | str,
        *,
        append: bool = False,
        detail: str = "",
    ) -> ActionRecord:
        """Write a file and record a WRITE action with its content hash.

        This is the ONLY sanctioned way for CompSuite to write to disk.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        raw = data.encode("utf-8") if isinstance(data, str) else data
        mode = "ab" if append else "wb"
        with p.open(mode) as fh:
            fh.write(raw)
            if self.flush_each_record:
                fh.flush()
                os.fsync(fh.fileno())
        return self.record(
            "WRITE",
            str(p.resolve()),
            sha256=sha256_bytes(raw),
            num_bytes=len(raw),
            detail=detail,
        )

    # ----- checkpoint ------------------------------------------------------

    def checkpoint(self, extra: Optional[dict] = None) -> None:
        """Persist run state so a restart is idempotent.

        Written via ``write_file`` so even the checkpoint write is traceable.
        """
        state = {
            "parent_run_id": self.parent_run_id,
            "seq": self._seq,
            "updated": _utc_now_iso(),
        }
        if extra:
            state.update(extra)
        self.write_file(
            self.log_dir / ".state.json",
            json.dumps(state, indent=2, sort_keys=True),
            detail="checkpoint",
        )

    @staticmethod
    def load_checkpoint(log_dir: os.PathLike | str) -> Optional[dict]:
        """Return the last checkpoint dict, or None if there isn't one."""
        p = Path(log_dir) / ".state.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None


def verify_record(record: ActionRecord, path: os.PathLike | str) -> bool:
    """Re-hash ``path`` and confirm it matches a record's ``sha256``.

    Lets an auditor confirm that the file on disk is the exact content the
    ledger claims was read/written. Returns False if the file is gone, the
    record had no hash, or the hash differs.
    """
    if record.sha256 is None:
        return False
    p = Path(path)
    if not p.is_file():
        return False
    return sha256_bytes(p.read_bytes()) == record.sha256
