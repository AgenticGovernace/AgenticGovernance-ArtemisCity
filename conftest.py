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

# Supabase tests mock their connection explicitly. The default suite must never
# reach a hosted database inherited from the operator's environment.
os.environ["ARTEMIS_VECTOR_BACKEND"] = "sqlite"
os.environ.pop("ARTEMIS_SUPABASE_DB_URL", None)
os.environ.pop("SUPABASE_DB_URL", None)


@atexit.register
def _remove_pytest_runtime_root() -> None:
    """Remove isolated test state after the Python test process exits."""
    shutil.rmtree(_PYTEST_RUNTIME_ROOT, ignore_errors=True)
