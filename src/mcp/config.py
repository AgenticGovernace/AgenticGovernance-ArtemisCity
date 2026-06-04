"""Configuration for the MCP layer.

Resolution order for every value (highest precedence first):
    1. Real process environment (e.g. exported shell vars, container env).
    2. ``Concept_Demos/.env`` — overrides the repo-root file for demo runs.
    3. Repo-root ``.env`` — shared defaults checked in alongside ``.env.example``.
    4. The hard-coded fallback in this file.

Variable names here are the public contract used by ``orchestrator.py``,
``web/api/main.py``, ``Concept_Demos/main.py``, and the test suite — keep them
in sync with ``.env.example``.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is pinned in Pipfile but degrade gracefully
    def load_dotenv(*_args, **_kwargs) -> bool:  # type: ignore[misc]
        """Provide a no-op ``load_dotenv`` fallback when python-dotenv is unavailable.
        Args:
            *_args: Positional arguments accepted for API compatibility with ``python-dotenv``.
            **_kwargs: Keyword arguments accepted for API compatibility with ``python-dotenv``.

        Returns:
            bool: Always returns ``False`` to indicate that no environment file was loaded.
        """
        return False

# config.py lives at <repo-root>/src/mcp/config.py, so parents[2] is the repo
# root. (Earlier indices were off-by-one — likely a leftover from when this
# file lived under Concept_Demos/src/mcp/.)
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[2]
_CONCEPT_DEMOS_ROOT = _REPO_ROOT / "Concept_Demos"

# Load lowest-precedence file first; ``override=False`` means anything already
# set in os.environ (real shell env or earlier .env) is preserved.
for _candidate in (_REPO_ROOT / ".env", _CONCEPT_DEMOS_ROOT / ".env"):
    if _candidate.is_file():
        load_dotenv(_candidate, override=False)

# --- Obsidian vault ---------------------------------------------------------
# OBSIDIAN_VAULT_PATH is the on-disk vault root. AGENT_INPUT_DIR /
# AGENT_OUTPUT_DIR are *vault-relative* folder names that callers join under
# the vault root via ObsidianManager (which does ``vault_path / relative``).
# Absolute defaults would collapse that join, escape the vault, and on Linux
# CI hit PermissionError on the runner's '/Users' (see #65).
OBSIDIAN_VAULT_PATH = os.getenv(
    "OBSIDIAN_VAULT_PATH",
    str(_REPO_ROOT / "obsidian_vault"),
)

# Vault-relative folder names. Callers MUST NOT join these onto
# OBSIDIAN_VAULT_PATH themselves; pass them straight to ObsidianManager methods.
AGENT_INPUT_DIR = os.getenv("AGENT_INPUT_DIR", "Agent Inputs")
AGENT_OUTPUT_DIR = os.getenv("AGENT_OUTPUT_DIR", "Agent Outputs")

# --- EXO cluster (local LLM inference) --------------------------------------
EXO_BASE_URL = os.getenv("EXO_BASE_URL", "http://localhost:52415")
EXO_MODEL_ID = os.getenv("EXO_MODEL_ID", "gpt-4o-2024-08-06")
