"""Ensure obsidian_integration is importable when running from this directory."""

from __future__ import annotations

import os
import sys


def _ensure_parent_on_syspath() -> None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)


_ensure_parent_on_syspath()
