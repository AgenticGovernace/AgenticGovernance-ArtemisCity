"""Session-wide guard that keeps pytest out of live Artemis runtime state.

The production defaults intentionally resolve to repository ``data/`` and
``logs/``. Tests exercise those same default constructors, so pytest must set
the umbrella roots before any test module imports an orchestrator, logger, or
governance store. Otherwise collection and coverage tests can silently mutate
live Hebbian, trust, registry, vector, and provenance data.
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

# Force isolation instead of using setdefault: a developer may deliberately
# point their shell at production data while running the live service, and a
# test command from that same shell must still be harmless.
os.environ["ARTEMIS_DATA_DIR"] = str(_PYTEST_DATA_DIR)
os.environ["ARTEMIS_LOG_DIR"] = str(_PYTEST_LOG_DIR)
os.environ["OBSIDIAN_VAULT_PATH"] = str(_PYTEST_VAULT_DIR)
os.environ["ARTEMIS_OBSIDIAN_VAULT_PATH"] = str(_PYTEST_VAULT_DIR)

# Keep unit tests off an operator's canonical SQL ledger and Obsidian REST
# credentials even when pytest inherits a live-service shell environment.
os.environ["ARTEMIS_MEMORY_BACKEND"] = "legacy"
os.environ.pop("ARTEMIS_MEMORY_DATABASE_URL", None)
os.environ.pop("ARTEMIS_MEMORY_MIGRATION_DATABASE_URL", None)
os.environ.pop("OBSIDIAN_API_KEY", None)
os.environ.pop("OBSIDIAN_CA_CERT", None)

# Pin the vector store to the local SQLite backend and drop any Supabase
# credentials so a test run from a Supabase-configured shell can never touch
# a live hosted database. Tests that exercise the Supabase backend must mock
# the connection layer explicitly.
os.environ["ARTEMIS_VECTOR_BACKEND"] = "sqlite"
os.environ.pop("ARTEMIS_SUPABASE_DB_URL", None)
os.environ.pop("SUPABASE_DB_URL", None)


@atexit.register
def _remove_pytest_runtime_root() -> None:
    """Remove isolated test state after the Python test process exits."""
    shutil.rmtree(_PYTEST_RUNTIME_ROOT, ignore_errors=True)
