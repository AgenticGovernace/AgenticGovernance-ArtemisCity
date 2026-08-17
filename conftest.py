"""Keep every pytest session out of live Artemis runtime state.

Production defaults intentionally resolve to repository ``data/`` and ``logs/``.
Tests exercise those default constructors, so isolation must be configured before
test modules import an orchestrator, logger, or governance store.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_PYTEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="artemis-city-pytest-")).resolve()
_PYTEST_DATA_DIR = _PYTEST_RUNTIME_ROOT / "data"
_PYTEST_LOG_DIR = _PYTEST_RUNTIME_ROOT / "logs"
_PYTEST_VAULT_DIR = _PYTEST_RUNTIME_ROOT / "vault"

for directory in (_PYTEST_DATA_DIR, _PYTEST_LOG_DIR, _PYTEST_VAULT_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# A test command from a shell configured for production must still be harmless.
os.environ["ARTEMIS_DATA_DIR"] = str(_PYTEST_DATA_DIR)
os.environ["ARTEMIS_LOG_DIR"] = str(_PYTEST_LOG_DIR)
os.environ["OBSIDIAN_VAULT_PATH"] = str(_PYTEST_VAULT_DIR)
os.environ["ARTEMIS_OBSIDIAN_VAULT_PATH"] = str(_PYTEST_VAULT_DIR)

# Redirecting only the vault root is not enough. AGENT_INPUT_DIR and
# AGENT_OUTPUT_DIR are joined *under* that root, so an operator .env carrying a
# path-prefixed value (for example "app/obsidian_vault/Agent_Outputs") is
# resolved relative to the vault and materializes a nested
# "<vault>/app/obsidian_vault/..." tree. Pin both to the documented
# vault-relative defaults so operator configuration drift cannot reach a test
# run or the live vault.
os.environ["AGENT_INPUT_DIR"] = "Agent Inputs"
os.environ["AGENT_OUTPUT_DIR"] = "Agent Outputs"

# Keep unit tests off an operator's canonical SQL ledger and Obsidian REST
# credentials even when pytest inherits a live-service shell environment.
os.environ["ARTEMIS_MEMORY_BACKEND"] = "legacy"
os.environ.pop("ARTEMIS_MEMORY_DATABASE_URL", None)
os.environ.pop("ARTEMIS_MEMORY_MIGRATION_DATABASE_URL", None)
os.environ.pop("OBSIDIAN_API_KEY", None)
os.environ.pop("OBSIDIAN_CA_CERT", None)

# Supabase tests mock their connection explicitly. The default suite must never
# reach a hosted database inherited from the operator's environment.
os.environ["ARTEMIS_VECTOR_BACKEND"] = "sqlite"
os.environ.pop("ARTEMIS_SUPABASE_DB_URL", None)
os.environ.pop("SUPABASE_DB_URL", None)


@atexit.register
def _remove_pytest_runtime_root() -> None:
    """Remove isolated test state after the Python test process exits."""
    shutil.rmtree(_PYTEST_RUNTIME_ROOT, ignore_errors=True)
