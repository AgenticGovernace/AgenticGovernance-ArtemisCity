"""Configuration for the MCP layer.

Resolution order for every value (highest precedence first):
    1. Real process environment (e.g. exported shell vars, container env).
    2. Repo-root ``.env`` — shared defaults checked in alongside ``.env.example``.
    3. The hard-coded fallback in this file.

Variable names here are the public contract used by ``orchestrator.py``,
``app/api/main.py``, ``src/launch/main.py``, and the test suite — keep them
in sync with ``.env.example``.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is a project dependency; degrade gracefully

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
# root.
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[2]

# Load lowest-precedence file first; ``override=False`` means anything already
# set in os.environ (real shell env or earlier .env) is preserved.
for _candidate in (_REPO_ROOT / ".env",):
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
EXO_MODEL_URL = os.getenv("EXO_MODEL_URL", "")
# Smallest text-generation model in the mlx-community registry (~327 MB)
# — fast first-token latency and a sensible default when no real Exo
# instance is configured. Override with EXO_MODEL_ID for production. The
# previous default ("gpt-4o-2024-08-06") was an OpenAI model name that no
# self-hosted Exo can serve, causing every call to 404.
EXO_MODEL_ID = os.getenv("EXO_MODEL_ID", "mlx-community/Qwen3-0.6B-4bit")
