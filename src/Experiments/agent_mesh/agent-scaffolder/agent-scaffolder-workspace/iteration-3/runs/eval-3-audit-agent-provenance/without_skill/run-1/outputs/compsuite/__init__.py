"""CompSuite — an unattended file-audit agent.

CompSuite watches ``voice_logs/`` and ``outputs/``, classifies every file
event as Normal / Warning / Error, escalates only above Warning, writes daily
audit logs, emits periodic reflection summaries, and records action-level
provenance for every read and write it performs.

The operating contract lives in ``AGENTS.md`` at the project root; this package
implements it.
"""

from __future__ import annotations

__all__ = [
    "provenance",
    "classifier",
    "escalation",
    "reflection",
    "watcher",
]

__version__ = "1.0.0"
