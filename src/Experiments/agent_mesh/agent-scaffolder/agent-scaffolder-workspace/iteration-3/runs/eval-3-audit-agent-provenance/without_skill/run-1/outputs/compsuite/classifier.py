"""Event classification: map a file event to Normal / Warning / Error.

The three severities and their ordering are defined here once and imported
everywhere else, so the escalation gate and the classifier can never disagree
about what "above Warning" means.

Classification rules are data-driven from ``config/compsuite.toml`` (see the
``[classification]`` table). The defaults encode the policy documented in
AGENTS.md §2.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Iterable, Optional


class Severity(IntEnum):
    """The only three severities, ordered Normal < Warning < Error."""

    NORMAL = 0
    WARNING = 1
    ERROR = 2

    @property
    def label(self) -> str:
        return {0: "Normal", 1: "Warning", 2: "Error"}[int(self)]

    @classmethod
    def from_label(cls, label: str) -> "Severity":
        key = label.strip().lower()
        table = {"normal": cls.NORMAL, "warning": cls.WARNING, "error": cls.ERROR}
        if key not in table:
            raise ValueError(f"unknown severity label: {label!r}")
        return table[key]


@dataclass(frozen=True)
class FileEvent:
    """A single observed change in a watched tree."""

    path: Path  # absolute, resolved path the event concerns
    kind: str  # "created" | "modified" | "moved" | "deleted"
    root: Path  # which watch root this path belongs to (resolved)
    size: Optional[int] = None  # bytes, when known (None for deletes)


@dataclass(frozen=True)
class Classification:
    """Result of classifying an event."""

    severity: Severity
    reason: str  # human-readable rule that fired


def _ext(path: Path) -> str:
    return path.suffix.lower()


def _is_within(path: Path, roots: Iterable[Path]) -> bool:
    rp = path.resolve()
    for root in roots:
        try:
            rp.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


def classify_event(
    event: FileEvent,
    *,
    watch_roots: Iterable[Path],
    voice_logs_allowed_ext: Iterable[str],
    outputs_allowed_ext: Iterable[str],
    forbidden_ext: Iterable[str],
    warn_on_unknown_extension: bool = True,
    warn_on_zero_byte: bool = True,
    warn_on_delete: bool = True,
    error_on_out_of_tree: bool = True,
) -> Classification:
    """Return the :class:`Classification` for ``event``.

    Order of checks matters: the most severe applicable rule wins. Errors are
    evaluated before Warnings so a forbidden extension is never downgraded.
    """
    ext = _ext(event.path)
    forbidden = {e.lower() for e in forbidden_ext}

    # --- ERROR-level checks first (most severe wins) ---------------------

    if error_on_out_of_tree and not _is_within(event.path, watch_roots):
        return Classification(
            Severity.ERROR,
            f"event path is outside every watch root: {event.path}",
        )

    if ext in forbidden:
        return Classification(
            Severity.ERROR,
            f"forbidden/executable extension {ext!r}",
        )

    # --- WARNING-level checks --------------------------------------------

    if warn_on_delete and event.kind == "deleted":
        return Classification(
            Severity.WARNING,
            f"watched file deleted ({event.path.name})",
        )

    if warn_on_zero_byte and event.size == 0 and event.kind != "deleted":
        return Classification(
            Severity.WARNING,
            "zero-byte file",
        )

    # Pick the allow-list for whichever root this path lives under.
    root_name = Path(event.root).name.lower()
    if "voice" in root_name:
        allowed = {e.lower() for e in voice_logs_allowed_ext}
    else:
        allowed = {e.lower() for e in outputs_allowed_ext}

    if warn_on_unknown_extension and ext and ext not in allowed:
        return Classification(
            Severity.WARNING,
            f"unexpected extension {ext!r} for root {Path(event.root).name!r}",
        )

    # --- NORMAL (steady state) -------------------------------------------

    return Classification(
        Severity.NORMAL,
        f"{event.kind} of allowed file {event.path.name}",
    )


def classify_safe(
    event: FileEvent, *, error_on_failure: bool = True, **rules
) -> Classification:
    """Classify, but never raise: on failure, fail loud as Error (policy).

    AGENTS.md §2 says a classifier failure is itself an Error so problems are
    surfaced rather than silently swallowed.
    """
    try:
        return classify_event(event, **rules)
    except Exception as exc:  # pragma: no cover - defensive
        if error_on_failure:
            return Classification(Severity.ERROR, f"classifier failure: {exc!r}")
        return Classification(
            Severity.WARNING, f"classifier failure (downgraded): {exc!r}"
        )
