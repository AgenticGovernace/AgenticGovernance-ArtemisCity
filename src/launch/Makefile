# ============================================
# ARTEMIS CITY - APPLICATION FEATURE LAUNCHER
# ============================================
# This Makefile intentionally owns feature execution only. Environments,
# dependencies, tests, services, builds, and docs belong to the root Makefile.

.PHONY: help run cli atp orchestrator kernel demo demo-artemis demo-memory \
        demo-postal hebbian agent-stats

.DEFAULT_GOAL := help

MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT_DIR := $(abspath $(MAKEFILE_DIR)/../..)
PYTHON ?= $(ROOT_DIR)/.venv/bin/python
ARGS ?=
AGENT ?=

LOAD_ENV = set -a; [ ! -f "$(ROOT_DIR)/.env" ] || . "$(ROOT_DIR)/.env"; set +a;

help: ## Show application feature commands
	@echo "Artemis City - Application Features"
	@echo "="
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

run: orchestrator ## Run the maintained orchestrator entry point

cli: ## Run the Artemis City kernel CLI
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) -m src $(ARGS)

atp: ## Run the ATP-enabled CLI
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) -m src --atp $(ARGS)

orchestrator: ## Run the MCP orchestrator pipeline
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) -m src --orchestrator $(ARGS)

kernel: ## Run the local kernel CLI
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) -m app.kernel.cli $(ARGS)

demo: demo-artemis demo-memory demo-postal ## Run all maintained demonstrations

demo-artemis: ## Run the Artemis feature demonstration
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) src/launch/demo_artemis.py

demo-memory: ## Run the memory integration demonstration
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) src/launch/demo_memory_integration.py

demo-postal: ## Run the city postal demonstration
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) src/launch/demo_city_postal.py

hebbian: ## Show the orchestrator Hebbian network summary
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) -m src --orchestrator --show-hebbian

agent-stats: ## Show Hebbian statistics for AGENT="<name>"
	@if [ -z "$(AGENT)" ]; then \
		echo 'ERROR: provide AGENT="<name>".' >&2; \
		exit 2; \
	fi
	cd "$(ROOT_DIR)" && $(LOAD_ENV) $(PYTHON) -m src --orchestrator --agent-stats "$(AGENT)"
