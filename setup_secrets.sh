#!/bin/bash
# Artemis City — complete runtime environment provisioner.
#
#   ./setup_secrets.sh              sync root-owned values to every service view
#   ./setup_secrets.sh --check      report missing keys or drift without writing
#   ./setup_secrets.sh --regenerate rotate only secrets owned by this repository

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

if [[ -n "${ARTEMIS_PYTHON:-}" ]]; then
    PYTHON_BIN="$ARTEMIS_PYTHON"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" "$REPO_ROOT/scripts/environment_config.py" setup "$@"
