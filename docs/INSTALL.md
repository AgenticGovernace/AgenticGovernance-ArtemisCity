# Installation Guide

This guide covers the supported Artemis City setup path.

## Prerequisites

- **Python**: 3.12
- **uv**: required for Python dependency installation
- **Node.js**: 20+ for the TypeScript API and React frontend
- **Git**: for cloning the repository
- **Obsidian**: with the Local REST API plugin when using vault-backed memory

Artemis City supports a root `.venv` created or validated by the root Makefile.
An existing Python 3.12 environment may be selected with explicit `VENV` and
`PYTHON` overrides, but dependency synchronization must still run through
`make install` or `make install-dev`. Do not use conda, Poetry, Pipenv, pyenv
range files, or direct pip-only installs for new repo setup instructions.

## Quick Install

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Artemis-City
```

### 2. Create Secrets

```bash
./setup_secrets.sh              # sync: heal drift, generate what's missing
./setup_secrets.sh --check      # read-only; exits 1 if any consumer is out of sync
./setup_secrets.sh --regenerate # rotate ALL canonical keys (use after a leak)
```

The script writes `.env`, `app/api/.env`, `src/.env`, and
`src/Artemis Agentic Memory Layer/.env` when that memory-layer directory exists.
It keeps one shared `MCP_API_KEY`, plus `FASTAPI_API_KEY` for the dashboard and
`ARTEMIS_API_KEY_DEFAULT` for the TypeScript Express API.

### 3. Install Python Dependencies

Recommended:

```bash
make install-dev
```

The root Makefile is the sole supported dependency installer. It creates or
validates the Python 3.12 environment, then synchronizes the committed
`uv.lock` in one transaction. To target an existing environment explicitly:

```bash
VENV=/absolute/path/to/.venv PYTHON=/absolute/path/to/.venv/bin/python make install-dev
```

### 4. Install Node Dependencies

Install both root-managed web workspaces from their shared lock:

```bash
make install-web
```

### 5. Verify Installation

```bash
make test
make run
python3.12 -m app.kernel.cli "system status"
```

## Common Commands

| Action | Command |
|---|---|
| Runtime dependencies | `make install` |
| Dev dependencies | `make install-dev` |
| API and frontend dependencies | `make install-web` |
| All development dependencies | `make install-all` |
| Tests | `make test` |
| Tests with coverage | `make test-cov` |
| FastAPI dashboard backend | `make api` |
| React frontend | `make frontend` |
| TypeScript Express API | `make express-api` |
| Kernel CLI probe | `python -m app.kernel.cli "system status"` |

## Environment Variables

After `./setup_secrets.sh`, set any optional service-specific values in `.env`:

```bash
OBSIDIAN_BASE_URL=http://localhost:27124
OBSIDIAN_API_KEY=your_obsidian_key_here
OBSIDIAN_VAULT_PATH=/absolute/path/to/vault
OPENAI_API_KEY=your_openai_key_here
ARTEMIS_ENV=dev
```

Never commit populated `.env` files.

## Updating Dependencies

Keep dependency changes explicit and lock-backed:

```bash
uv lock --upgrade-package <package>
uv lock --upgrade
make install-dev
```

When changing package manifests or lock-style requirements, run the relevant
tests before committing:

```bash
make test
```

## Troubleshooting

### Wrong Python Version

```bash
cat .python-version
python --version
```

The repo pin is Python 3.12. Recreate the environment if it was built with a
different interpreter:

```bash
rm -rf .venv
make venv
source .venv/bin/activate
make install-dev
```

### Missing uv

Install uv using your system package manager or the official uv installer, then
rerun `make install-dev`.

### Import Errors

Confirm that the active interpreter is the project virtual environment:

```bash
which python
python -c "import src; print('src import OK')"
```

Then reinstall through the root dependency owner:

```bash
make install-dev
```
