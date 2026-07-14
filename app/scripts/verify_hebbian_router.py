#!/usr/bin/env python3
"""Run the authoritative Hebbian routing tests from any checkout location."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    raise SystemExit(
        subprocess.call(
            [sys.executable, "-m", "pytest", "-q", "src/tests/test_hebbian_router.py"],
            cwd=REPO_ROOT,
        )
    )
