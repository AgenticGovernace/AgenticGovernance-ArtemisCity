"""MCP layer exports: orchestrator, config, and memory-learning utilities.

This package is normally imported as ``src.mcp``. Some IDEs accidentally run
``src/mcp/__init__.py`` as a script, which removes package context and breaks
relative imports. In that direct-execution mode, delegate to the orchestrator
CLI instead of raising an opaque import error.
"""

from __future__ import annotations

from importlib import import_module


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

from . import config  # noqa: E402  (direct-execution guard must run first)
from .config import (  # noqa: E402  (direct-execution guard must run first)
    AGENT_INPUT_DIR,
    AGENT_OUTPUT_DIR,
    OBSIDIAN_VAULT_PATH,
)

_LAZY_EXPORTS = {
    "Orchestrator": (".orchestrator", "Orchestrator"),
    "HebbianWeightManager": (".hebbian_weights", "HebbianWeightManager"),
    "LocalVectorStore": (".vector_store", "LocalVectorStore"),
    "VectorRecord": (".vector_store", "VectorRecord"),
    "create_vector_store": (".vector_store", "create_vector_store"),
    "SupabaseVectorStore": (".supabase_vector_store", "SupabaseVectorStore"),
}


def __getattr__(name: str):
    """Load heavyweight MCP exports only when they are requested."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY_EXPORTS})


__all__ = [
    "Orchestrator",
    "HebbianWeightManager",
    "LocalVectorStore",
    "VectorRecord",
    "OBSIDIAN_VAULT_PATH",
    "AGENT_INPUT_DIR",
    "AGENT_OUTPUT_DIR",
    "config",
]
