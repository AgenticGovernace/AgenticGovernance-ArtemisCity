#!/usr/bin/env python3
"""Compatibility shim for the city postal walkthrough.

The maintained implementation lives in ``src/launch/demo_city_postal.py``.
"""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "src"
            / "launch"
            / "demo_city_postal.py"
        ),
        run_name="__main__",
    )
