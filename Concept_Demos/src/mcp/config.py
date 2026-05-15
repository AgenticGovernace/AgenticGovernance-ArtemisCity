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
        return False

_THIS_FILE = Path(__file__).resolve()
_CONCEPT_DEMOS_ROOT = _THIS_FILE.parents[2]  # .../Concept_Demos
_REPO_ROOT = _THIS_FILE.parents[3]  # .../AgenticGovernance-ArtemisCity

# Load lowest-precedence file first; ``override=False`` means anything already
# set in os.environ (real shell env or earlier .env) is preserved.
for _candidate in (_REPO_ROOT / ".env", _CONCEPT_DEMOS_ROOT / ".env"):
    if _candidate.is_file():
        load_dotenv(_candidate, override=False)

# --- Obsidian vault ---------------------------------------------------------
OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH",
                                "/Users/prinstonpalmer/PycharmProjects/FastAPIProject/obsidian_vault")

# Agents read tasks from AGENT_INPUT_DIR and write reports to AGENT_OUTPUT_DIR.
# These are resolved relative to OBSIDIAN_VAULT_PATH by the orchestrator.
AGENT_INPUT_DIR = os.getenv("AGENT_INPUT_DIR",
                            "/Users/prinstonpalmer/PycharmProjects/FastAPIProject/obsidian_vault/Agent Inputs")
AGENT_OUTPUT_DIR = os.getenv("AGENT_OUTPUT_DIR",
                             "/Users/prinstonpalmer/PycharmProjects/FastAPIProject/obsidian_vault/Agent Outputs")

# --- EXO cluster (local LLM inference) --------------------------------------
EXO_BASE_URL = os.getenv("EXO_BASE_URL", "http://localhost:52415")
EXO_MODEL_ID = os.getenv("EXO_MODEL_ID", "gpt-4o-2024-08-06")
