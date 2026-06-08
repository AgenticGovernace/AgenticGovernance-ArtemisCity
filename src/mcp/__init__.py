"""MCP layer exports: orchestrator, config, and memory-learning utilities.

This package is normally imported as ``src.mcp``. Some IDEs accidentally run
``src/mcp/__init__.py`` as a script, which removes package context and breaks
relative imports. In that direct-execution mode, delegate to the orchestrator
CLI instead of raising an opaque import error.
"""

from __future__ import annotations


def _run_as_script() -> None:
    """Run the orchestrator CLI when this package file is executed directly."""
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)

    from src.launch.main import main

    raise SystemExit(main())


if __name__ == "__main__" and not __package__:
    _run_as_script()

from .config import AGENT_INPUT_DIR, AGENT_OUTPUT_DIR, OBSIDIAN_VAULT_PATH
from .hebbian_weights import HebbianWeightManager
from .orchestrator import Orchestrator
from .vector_store import LocalVectorStore, VectorRecord

__all__ = [
    "Orchestrator",
    "HebbianWeightManager",
    "LocalVectorStore",
    "VectorRecord",
    "OBSIDIAN_VAULT_PATH",
    "AGENT_INPUT_DIR",
    "AGENT_OUTPUT_DIR",
]
