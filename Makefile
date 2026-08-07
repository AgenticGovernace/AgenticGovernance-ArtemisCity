# ============================================
# ARTEMIS CITY - ROOT DEVELOPMENT CONTRACT
# ============================================
# The root Makefile exclusively owns environments, dependency installation,
# validation, packaging, documentation, and service launches. Application
# feature commands are delegated to src/launch/Makefile.

.PHONY: help venv install install-dev install-web install-all setup-hooks \
        lint lint-fix format check security secrets test test-cov \
        pre-commit pre-commit-update clean clean-env \
        run cli atp orchestrator kernel demo demo-artemis demo-memory demo-postal \
        hebbian agent-stats server frontend api dashboard-api express-api \
        legal-summarization legal-summarization-check \
        build web-build docs docs-serve all ci

.DEFAULT_GOAL := help

MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT_DIR := $(abspath $(MAKEFILE_DIR))
LAUNCH_DIR := $(ROOT_DIR)/src/launch
MEMORY_SERVER_DIR := $(ROOT_DIR)/src/Artemis Agentic Memory Layer

PYTHON_VERSION ?= 3.12
VENV ?= $(ROOT_DIR)/.venv
PYTHON ?= $(VENV)/bin/python
UV ?= uv
NPM ?= npm
ARGS ?=
AGENT ?=

# Export root .env values only for the process launched by the recipe.
LOAD_ENV = set -a; [ ! -f "$(ROOT_DIR)/.env" ] || . "$(ROOT_DIR)/.env"; set +a;

# ============================================
# HELP
# ============================================

help: ## Show this help message
	@echo "Artemis City - Available Commands"
	@echo "="
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ============================================
# INSTALLATION - ROOT OWNERSHIP ONLY
# ============================================

venv: ## Create or validate the canonical Python 3.12 environment
	@if [ ! -x "$(PYTHON)" ]; then \
		$(UV) venv --python $(PYTHON_VERSION) "$(VENV)"; \
	elif ! "$(PYTHON)" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))'; then \
		echo "ERROR: $(PYTHON) is not Python 3.12. Recreate $(VENV) before installing." >&2; \
		exit 1; \
	else \
		echo "Using existing environment: $(PYTHON)"; \
	fi

install: venv ## Install locked runtime dependencies into the root environment
	@echo "Synchronizing runtime dependencies into $(PYTHON)..."
	cd "$(ROOT_DIR)" && VIRTUAL_ENV="$(VENV)" UV_PROJECT_ENVIRONMENT="$(VENV)" \
		$(UV) sync --locked --no-default-groups --python $(PYTHON)

install-dev: venv ## Install runtime and all locked development extras in one transaction
	@echo "Synchronizing runtime and development dependencies into $(PYTHON)..."
	cd "$(ROOT_DIR)" && VIRTUAL_ENV="$(VENV)" UV_PROJECT_ENVIRONMENT="$(VENV)" \
		$(UV) sync --locked --all-extras --python $(PYTHON)

install-web: ## Install API and frontend workspace dependencies from the root lock
	cd "$(ROOT_DIR)" && $(NPM) ci --workspaces --include-workspace-root

install-all: install-dev install-web ## Install canonical Python and web dependencies

setup-hooks: ## Configure pre-commit hooks from the installed root environment
	cd "$(ROOT_DIR)" && $(PYTHON) -m pre_commit install

# ============================================
# CODE QUALITY
# ============================================

lint: ## Reject undefined Python names using the promotion gate
	cd "$(ROOT_DIR)" && $(PYTHON) -m ruff check src app/api/main.py \
		--select F821 --exclude '**/.virtual_documents/**'

lint-fix: ## Apply safe fixes for the promotion lint gate and format Python
	cd "$(ROOT_DIR)" && $(PYTHON) -m ruff check --fix src app/api/main.py \
		--select F821 --exclude '**/.virtual_documents/**'
	cd "$(ROOT_DIR)" && $(PYTHON) -m black src app
	cd "$(ROOT_DIR)" && $(PYTHON) -m isort src app

format: ## Format Python source with Black and isort
	cd "$(ROOT_DIR)" && $(PYTHON) -m black src app
	cd "$(ROOT_DIR)" && $(PYTHON) -m isort src app

check: lint ## Run formatting, import-order, and type checks
	cd "$(ROOT_DIR)" && $(PYTHON) -m black --check src app
	cd "$(ROOT_DIR)" && $(PYTHON) -m isort --check-only src app
	cd "$(ROOT_DIR)" && $(PYTHON) -m mypy src app

security: ## Run dependency and source security checks
	cd "$(ROOT_DIR)" && $(PYTHON) -m bandit -r src app -c pyproject.toml
	cd "$(ROOT_DIR)" && $(PYTHON) -m safety check

secrets: ## Check staged changes for common secret names
	@git diff --cached --name-only | xargs grep -l "API_KEY\|SECRET\|PASSWORD" 2>/dev/null \
		&& echo "WARNING: Potential secrets detected!" || echo "No secrets detected"

# ============================================
# TESTING
# ============================================

test: ## Run the canonical Python test suite
	cd "$(ROOT_DIR)" && $(PYTHON) -m pytest src/tests

test-cov: ## Run tests with terminal and HTML coverage reports
	cd "$(ROOT_DIR)" && $(PYTHON) -m pytest src/tests --cov --cov-report=html --cov-report=term

# ============================================
# PRE-COMMIT
# ============================================

pre-commit: ## Run all configured pre-commit hooks
	cd "$(ROOT_DIR)" && $(PYTHON) -m pre_commit run --all-files

pre-commit-update: ## Update configured pre-commit hooks
	cd "$(ROOT_DIR)" && $(PYTHON) -m pre_commit autoupdate

# ============================================
# CLEANUP
# ============================================

clean: ## Remove generated build, cache, coverage, and documentation output
	find "$(ROOT_DIR)" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find "$(ROOT_DIR)" -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find "$(ROOT_DIR)" -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find "$(ROOT_DIR)" -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find "$(ROOT_DIR)" -type f \( -name "*.pyc" -o -name "*.pyo" -o -name ".coverage" \) -delete
	rm -rf "$(ROOT_DIR)/build" "$(ROOT_DIR)/dist" "$(ROOT_DIR)/.tox" \
		"$(ROOT_DIR)/htmlcov" "$(ROOT_DIR)/.coverage"

clean-env: ## Safely remove one validated virtual environment
	@target="$(VENV)"; \
	if [ -z "$$target" ]; then \
		echo "ERROR: Refusing to remove unsafe environment path: empty target." >&2; \
		exit 2; \
	fi; \
	if [ -L "$$target" ]; then \
		echo "ERROR: Refusing to remove a symbolic link: $$target" >&2; \
		exit 2; \
	fi; \
	if [ ! -e "$$target" ]; then \
		echo "No environment to remove: $$target"; \
		exit 0; \
	fi; \
	if [ ! -d "$$target" ] || [ ! -f "$$target/pyvenv.cfg" ]; then \
		echo "ERROR: Refusing to remove unsafe environment path without pyvenv.cfg: $$target" >&2; \
		exit 2; \
	fi; \
	resolved="$$(cd "$$target" && pwd -P)" || exit 2; \
	case "$$resolved" in \
		"/"|"$(ROOT_DIR)"|"$${HOME:-}") \
			echo "ERROR: Refusing to remove unsafe environment path: $$resolved" >&2; \
			exit 2 ;; \
	esac; \
	rm -rf -- "$$resolved"; \
	echo "Removed virtual environment: $$resolved"

# ============================================
# APPLICATION FEATURES - DELEGATED TO src/launch
# ============================================

run: ## Run the orchestrator feature entry point
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" run ARGS="$(ARGS)"

cli: ## Run the Artemis City CLI
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" cli ARGS="$(ARGS)"

atp: ## Run the ATP CLI
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" atp ARGS="$(ARGS)"

orchestrator: ## Run the MCP orchestrator pipeline
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" orchestrator ARGS="$(ARGS)"

kernel: ## Run the local kernel CLI
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" kernel ARGS="$(ARGS)"

demo: ## Run all maintained launch demonstrations
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" demo

demo-artemis: ## Run the Artemis feature demonstration
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" demo-artemis

demo-memory: ## Run the memory integration demonstration
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" demo-memory

demo-postal: ## Run the city postal demonstration
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" demo-postal

hebbian: ## Show the orchestrator Hebbian network summary
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" hebbian

agent-stats: ## Show Hebbian statistics for AGENT="<name>"
	+$(MAKE) --no-print-directory -C "$(LAUNCH_DIR)" agent-stats AGENT="$(AGENT)"

# ============================================
# SERVICES
# ============================================

server: ## Start the standalone memory server when its package is available
	@if [ ! -f "$(MEMORY_SERVER_DIR)/package.json" ]; then \
		echo "ERROR: The standalone memory-server package is not present in this checkout." >&2; \
		exit 1; \
	fi
	cd "$(MEMORY_SERVER_DIR)" && $(NPM) run dev

frontend: ## Start the Vite frontend on :5173; run make api separately
	cd "$(ROOT_DIR)" && $(NPM) run frontend:dev

dashboard-api: ## Start the FastAPI dashboard backend on :8000
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) -m uvicorn app.api.main:app \
		--reload --host 0.0.0.0 --port 8000

api: dashboard-api ## Compatibility alias for the FastAPI dashboard backend

express-api: ## Start the TypeScript Express boundary on :4000
	cd "$(ROOT_DIR)" && $(NPM) run api:dev

legal-summarization: ## Run legal summarization with ARGS="..."
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) -m src.Experiments.legal_summarization.main $(ARGS)

legal-summarization-check: ## Check legal evaluation dependencies without running a model
	cd "$(ROOT_DIR)" && $(PYTHON) -m src.Experiments.legal_summarization.main --check-dependencies

# ============================================
# BUILD AND DOCUMENTATION
# ============================================

build: ## Build the Python package
	cd "$(ROOT_DIR)" && $(PYTHON) -m build

web-build: ## Build the Express API and Vite frontend
	cd "$(ROOT_DIR)" && $(NPM) run build

docs: ## Build documentation and fail on configuration or content warnings
	cd "$(ROOT_DIR)" && $(PYTHON) -m mkdocs build --strict

docs-serve: ## Serve documentation locally
	cd "$(ROOT_DIR)" && $(PYTHON) -m mkdocs serve

# ============================================
# AGGREGATES
# ============================================

all: install-all check security test docs ## Install dependencies and run Python/docs quality gates

ci: lint test docs ## Run the promotion Python/docs gates
