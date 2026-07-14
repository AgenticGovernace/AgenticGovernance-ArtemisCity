# ============================================
# ARTEMIS CITY - MAKEFILE
# ============================================
# Convenient commands for development tasks
# Usage: make <target>

.PHONY: help venv install install-dev setup-hooks lint lint-fix format check security secrets \
        test test-cov pre-commit pre-commit-update clean clean-env run cli demo server \
        frontend build docs docs-serve all ci

# Default target
.DEFAULT_GOAL := help

# Load root .env values for local Python entry points. The setup script writes
# the Python core's MCP_API_KEY/MCP_BASE_URL there, but make does not export
# .env files automatically.
LOAD_ENV = set -a; [ ! -f .env ] || . ./.env; set +a;
PYTHON_VERSION ?= 3.12
VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
UV ?= uv
ROOT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

# ============================================
# HELP
# ============================================

help: ## Show this help message
	@echo "Artemis City - Available Commands"
	@echo "="
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ============================================
# INSTALLATION
# ============================================

venv: ## Create the Python 3.12 virtual environment with uv
	$(UV) venv --python $(PYTHON_VERSION) $(VENV)

install:  ## Install runtime dependencies with uv
	echo "Installing Python dependencies..."
	UV add -r ./requirements.txt 
	echo "Installation complete!"

install-dev:  ## Install runtime and development dependencies with uv
	echo "Installing development dependencies..."
	uv pip install -r requirements.txt -r requirements-dev.txt
	uv pip install -e . 
	@echo "Development dependencies installed!"

setup-hooks: venv ## Install pre-commit hooks into the uv-managed virtual environment
	@echo "Installing pre-commit hooks..."
	$(UV) pip install --python $(PYTHON) pre-commit
	$(PYTHON) -m pre_commit install
	@echo "Pre-commit hooks installed!"

# ============================================
# CODE QUALITY
# ============================================

lint: ## Run all linters
	@echo "Running linters..."
	@echo "\n--- Flake8 ---"
	flake8 src/ app/ || true
	@echo "\n--- Pylint ---"
	pylint src/ app/ || true
	@echo "\nLinting complete!"

lint-fix: ## Run linters with auto-fix
	@echo "Running linters with auto-fix..."
	@echo "\n--- Black (formatter) ---"
	black .
	@echo "\n--- isort (import sorter) ---"
	isort .
	@echo "\nAuto-fix complete!"

format: lint-fix ## Format code (alias for lint-fix)

check: ## Run all checks (format, lint, type)
	@echo "Running all checks..."
	@echo "\n--- Black (check only) ---"
	black --check .
	@echo "\n--- isort (check only) ---"
	isort --check-only .
	@echo "\n--- Flake8 ---"
	flake8 .
	@echo "\n--- MyPy (type checking) ---"
	mypy . || true
	@echo "\nAll checks complete!"

# ============================================
# SECURITY
# ============================================


security: ## Run security checks
	@echo "Running security checks..."
	@echo "\n--- Bandit (security scanner) ---"
	cd "$(ROOT_DIR)" && bandit -r . -c pyproject.toml || true
	@echo "\n--- Safety (dependency vulnerabilities) ---"
	safety check || true
	@echo "\nSecurity checks complete!"

secrets: ## Check for accidentally committed secrets
	@echo "Checking for secrets..."
	@git diff --cached --name-only | xargs grep -l "API_KEY\|SECRET\|PASSWORD" 2>/dev/null \
		&& echo "WARNING: Potential secrets detected!" || echo "No secrets detected"

# ============================================
# TESTING
# ============================================

test: ## Run tests (when available)
	@echo "Running tests..."
	@if [ ! -d src/tests ]; then \
		echo "WARNING: No tests directory found"; \
	else \
		$(PYTHON) -m pytest src/tests/ -v; \
	fi

test-cov: ## Run tests with coverage
	@echo "Running tests with coverage..."
	@if [ ! -d src/tests ]; then \
		echo "WARNING: No tests directory found"; \
	else \
		$(PYTHON) -m pytest src/tests/ --cov=src --cov=app --cov-report=html --cov-report=term; \
	fi

# ============================================
# PRE-COMMIT
# ============================================

pre-commit: ## Run pre-commit hooks on all files
	@echo "Running pre-commit hooks..."
	pre-commit run --all-files

pre-commit-update: ## Update pre-commit hooks
	@echo "Updating pre-commit hooks..."
	pre-commit autoupdate

# ============================================
# CLEANUP
# ============================================

clean: ## Remove build artifacts and cache files
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name "*.coverage" -delete 2>/dev/null || true
	rm -rf build/ dist/ .tox/ htmlcov/ .coverage
	@echo "Cleanup complete!"

clean-env: ## Remove virtual environment
	@echo "Removing virtual environment..."
	rm -rf .venv venv
	@echo "Virtual environment removed!"

# ============================================
# DEVELOPMENT
# ============================================

run: ## Run the CLI interactively
	@echo "Starting Artemis City CLI..."
	@$(LOAD_ENV) $(PYTHON) src/launch/main.py

cli: ## Run the legacy Artemis CLI
	@echo "Starting Artemis CLI..."
	@$(LOAD_ENV) $(PYTHON) -m src.interface.artemis_cli

demo: ## Run all demos
	@echo "Running demos..."
	@echo "\n--- Artemis Features Demo ---"
	@$(LOAD_ENV) $(PYTHON) src/launch/demo_artemis.py
	@echo "\n--- Memory Integration Demo ---"
	@$(LOAD_ENV) $(PYTHON) src/launch/demo_memory_integration.py
	@echo "\n--- City Postal Demo ---"
	@$(LOAD_ENV) $(PYTHON) src/launch/demo_city_postal.py
	@echo "\nDemos complete!"

server: ## Start MCP server (Memory Layer)
	@echo "Starting MCP server..."
	cd "src/Artemis Agentic Memory Layer" && npm run dev

frontend: ## Start the web frontend dev server (needs `make api` running separately on :8000)
	@echo "Starting frontend dev server..."
	@echo "NOTE: also run 'make api' in another terminal so /api/* requests resolve."
	cd app/web/frontend && npm run dev

api: ## Start the FastAPI dashboard backend on :8000 (paired with `make frontend`)
	@echo "Starting FastAPI dashboard backend on http://localhost:8000 ..."
	@$(LOAD_ENV) $(PYTHON) -m uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000

# ============================================
# BUILD & PACKAGE
# ============================================

build: ## Build the package
	@echo "Building package..."
	$(PYTHON) -m build
	@echo "Build complete!"

# ============================================
# DOCUMENTATION
# ============================================

docs: ## Build documentation (if available)
	@echo "Building documentation..."
	mkdocs build || echo "WARNING: MkDocs not configured"

docs-serve: ## Serve documentation locally
	@echo "Serving documentation..."
	mkdocs serve || echo "WARNING: MkDocs not configured"

# ============================================
# ALL-IN-ONE COMMANDS
# ============================================

all: clean install-dev format lint security test ## Run all quality checks
	@echo "All tasks complete!"

ci: check test ## Run CI checks (format check, lint, test)
	@echo "CI checks complete!"
