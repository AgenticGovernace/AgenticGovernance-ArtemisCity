# Installation Guide

This guide covers the supported Artemis City setup path.

## Prerequisites

- **Python**: 3.12
- **uv**: required for Python dependency installation
- **Node.js**: 18+ for TypeScript services and the standalone memory layer
- **Git**: for cloning the repository
- **Obsidian**: with the Local REST API plugin when using vault-backed memory

Artemis City supports only two local Python environment shapes:

1. A `.venv` created by `uv`.
2. A `.venv` created by `venv` or `virtualenv`, with dependencies installed by
   `uv pip`.

Do not use conda, poetry, pyenv range files, or direct pip-only installs for new
repo setup instructions.

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

Equivalent manual setup with uv:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt
```

Manual setup with an existing virtual environment tool:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt
```

`virtualenv --python python3.12 .venv` is also supported when `virtualenv` is
already installed.

### 4. Install Node Dependencies

Root API/dashboard tooling:

```bash
npm install
```

Standalone Obsidian MCP memory layer:

```bash
cd "src/Artemis Agentic Memory Layer"
npm install
```

### 5. Verify Installation

```bash
make test
make run
python -m app.kernel.cli "system status"
```

## Common Commands

| Action | Command |
|---|---|
| Runtime dependencies | `make install` |
| Dev dependencies | `make install-dev` |
| Tests | `make test` |
| Tests with coverage | `make test-cov` |
| FastAPI dashboard backend | `make api` |
| React frontend | `make frontend` |
| Standalone memory server | `make server` |
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

Keep dependency changes explicit and uv-backed:

```bash
uv pip install --python .venv/bin/python -r requirements.txt -r requirements-dev.txt --upgrade
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
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-dev.txt
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

Then reinstall with uv:

```bash
uv pip install -r requirements.txt -r requirements-dev.txt
```
