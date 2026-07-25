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


def _vault_relative_dir(
    value: str, *, vault_path: str, legacy_name: str | None = None
) -> str:
    """Normalize a configured folder to a safe vault-relative path.

    Older local ``.env`` files used absolute input/output paths. Preserve that
    configuration only when the path is genuinely inside the configured
    vault; paths outside the vault and parent traversals fail closed.
    """
    requested = Path(value).expanduser()
    vault_root = Path(vault_path).expanduser().resolve()
    if requested.is_absolute():
        candidate = requested.resolve()
    else:
        if ".." in requested.parts:
            raise ValueError("agent folder paths must remain within the Obsidian vault")
        candidate = (vault_root / requested).resolve()
    try:
        relative = candidate.relative_to(vault_root)
    except ValueError as exc:
        # Test/deployment harnesses commonly override only the vault root while
        # a legacy .env still holds the old absolute default folder. Redirect
        # that exact known folder name into the new vault; never retain the
        # outside absolute location.
        if requested.is_absolute() and legacy_name and requested.name == legacy_name:
            return legacy_name
        raise ValueError(
            "agent folder paths must remain within the Obsidian vault"
        ) from exc
    if not relative.parts:
        raise ValueError("agent folder paths must name a folder within the vault")
    return relative.as_posix()


# Vault-relative folder names. Callers MUST NOT join these onto
# OBSIDIAN_VAULT_PATH themselves; pass them straight to ObsidianManager methods.
AGENT_INPUT_DIR = _vault_relative_dir(
    os.getenv("AGENT_INPUT_DIR", "Agent Inputs"),
    vault_path=OBSIDIAN_VAULT_PATH,
    legacy_name="Agent Inputs",
)
AGENT_OUTPUT_DIR = _vault_relative_dir(
    os.getenv("AGENT_OUTPUT_DIR", "Agent Outputs"),
    vault_path=OBSIDIAN_VAULT_PATH,
    legacy_name="Agent Outputs",
)

# --- EXO cluster (local LLM inference) --------------------------------------
EXO_BASE_URL = os.getenv("EXO_BASE_URL", "http://localhost:52415")
EXO_MODEL_URL = os.getenv("EXO_MODEL_URL", "")
# Smallest text-generation model in the mlx-community registry (~327 MB)
# — fast first-token latency and a sensible default when no real Exo
# instance is configured. Override with EXO_MODEL_ID for production. The
# previous default ("gpt-4o-2024-08-06") was an OpenAI model name that no
# self-hosted Exo can serve, causing every call to 404.
EXO_MODEL_ID = os.getenv("EXO_MODEL_ID") or "mlx-community/Qwen3-0.6B-4bit"
