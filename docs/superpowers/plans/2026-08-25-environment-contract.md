# Environment Contract Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for every behavior change. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace drift-prone environment YAML and Bash-only secret handling with one validated policy, provisioning, hook, and live-check contract spanning every maintained runtime.

**Architecture:** `src.utils.environments` validates policy-only profiles while `scripts/environment_config.py` consumes a machine-readable contract for source checks, safe fixes, provisioning, and live probes. `setup_secrets.sh`, Make, pre-commit, Docker Compose, and promotion CI are thin callers of those shared behaviors.

**Tech Stack:** Python 3.12, PyYAML, pytest, Bash compatibility wrapper, pre-commit, Make, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-25-environment-contract-design.md`

## Global Constraints

- Preserve all unrelated dirty-worktree changes; do not stage, revert, or commit them.
- Never print or fabricate operator secrets, endpoints, database URLs, identities, or model selections.
- `config/environments/` is the sole policy source. The held
  `.github/environments/` snapshots must remain byte-for-byte unchanged and
  outside every runtime/checker input until the reverse-sync hold is released.
- `load_environment()` keeps returning `dict[str, Any]`.
- Hook auto-fix may change tracked policy sources only; populated `.env` files change only through explicit setup.
- Pull requests receive deterministic source checks; live validation runs at pre-push and in protected staging/prod jobs.

---

### Task 1: Typed policy profiles and deterministic source validation

**Files:**
- Create: `src/tests/test_environments.py`
- Create: `src/tests/test_environment_config.py`
- Create: `config/environment-contract.yaml`
- Create: `scripts/environment_config.py`
- Modify: `src/utils/environments.py`
- Modify: `config/environments/dev.yaml`
- Modify: `config/environments/staging.yaml`
- Modify: `config/environments/prod.yaml`
- Preserve unchanged: `.github/environments/dev.yaml`, `.github/environments/staging.yaml`, `.github/environments/prod.yaml`

**Interfaces:**
- `normalize_environment_name(name: str) -> str`
- `validate_environment_profile(data: Mapping[str, Any], expected_name: str) -> dict[str, Any]`
- `load_environment(name: str | None = None) -> dict[str, Any]`
- CLI `check` exits 0 only when profiles, targets, templates, and source inventory agree.
- CLI `fix` rewrites only deterministic known drift and exits nonzero on ambiguous fields.

- [ ] **Step 1: Write failing profile tests** for explicit-name normalization, traversal rejection, schema/type errors, filename identity, policy-only fields, and all three real profiles.
- [ ] **Step 2: Run RED:** `./.venv/bin/python -m pytest -q -p no:cacheprovider src/tests/test_environments.py`; expect failures because validation APIs and policy-only profiles do not exist.
- [ ] **Step 3: Implement minimal loader validation** with path validation before `_config_path()`, literal schema checks, and dictionary return compatibility.
- [ ] **Step 4: Write failing source-check tests** using temporary repositories/templates; each test names one break: duplicate keys, a discovered code variable absent from the root template, runtime values in a canonical profile, and non-idempotent fix. Held `.github/environments` snapshots are explicitly outside checker input.
- [ ] **Step 5: Run RED:** `./.venv/bin/python -m pytest -q -p no:cacheprovider src/tests/test_environment_config.py`; expect missing CLI/contract failures.
- [ ] **Step 6: Implement `check` and `fix`** plus the contract target registry. Source discovery covers maintained Python/TS/Bash/Compose files and excludes tests, archives, experiments, examples, virtual environments, vendored dependencies, and generated artifacts.
- [ ] **Step 7: Replace the three canonical profiles** with the exact spec shape while preserving the held `.github/environments` snapshots unchanged.
- [ ] **Step 8: Run GREEN:** both focused test files pass, and running `fix` twice produces no second diff.

### Task 2: Full root provisioning and generated service views

**Files:**
- Modify: `src/tests/test_setup_secrets.py`
- Modify: `scripts/environment_config.py`
- Modify: `setup_secrets.sh`
- Modify: `.env.example`
- Modify: `app/api/.env.example`
- Modify: `src/.env.example`
- Modify: `src/Artemis Agentic Memory Layer/.env.example`
- Create: `services/mcp/artemis-memory/.env.example`
- Create: `config/service-env/provenance.env.example` (tracked template for the ignored nested provenance checkout)

**Interfaces:**
- CLI `setup`, `setup --check`, and `setup --regenerate` preserve the wrapper's exit-code contract.
- Root `.env` is reconciled first; every service target is a minimal view sourced from root values for matching keys.
- Contract ownership lists generated secrets and derived mappings; every other
  template value is operator-owned or a non-secret default.

- [ ] **Step 1: Extend setup tests first** to require seven targets, root-to-view propagation, operator-value preservation, generated-secret rotation, `0600` permissions, duplicate-key rejection, and no subprocess use of `awk`, `sed`, or `grep` for `.env` reads.
- [ ] **Step 2: Run RED:** `./.venv/bin/python -m pytest -q -p no:cacheprovider src/tests/test_setup_secrets.py`; confirm failures are the new behavior or the known sandbox-killed Bash parser.
- [ ] **Step 3: Implement Python env parsing and reconciliation** without external readers, preserving comments/order where possible and redacting all diagnostics.
- [ ] **Step 4: Make `setup_secrets.sh` a thin `/bin/bash` compatibility wrapper** that selects `.venv/bin/python` when available, otherwise `python3`, and delegates all modes.
- [ ] **Step 5: Complete the root template inventory** by adding code-discovered routing/delegation/Prometheus fields, memory MCP stdio/HTTP identity groups, provenance/proxy fields, and removing duplicate declarations. Add minimal service templates whose keys are subsets of root.
- [ ] **Step 6: Run GREEN:** setup tests pass and `environment_config.py check` reports no source/template drift.

### Task 3: Live validation, hooks, Compose, and protected promotion gates

**Files:**
- Modify: `src/tests/test_environment_config.py`
- Modify: `src/tests/test_docker_compose.py`
- Modify: `scripts/environment_config.py`
- Modify: `Makefile`
- Modify: `.pre-commit-config.yaml`
- Modify: `docker-compose.yaml`
- Modify: `.github/workflows/promote.yml`

**Interfaces:**
- CLI `live --env <name> --env-file <path>` and Make target `env-live-check`.
- HTTP probe results are `service`, `status`, and redacted `reason`; database probe runs `SELECT 1` and never echoes its DSN.
- Pre-commit stage runs `make env-fix`; pre-push stage runs `make env-live-check`.

- [ ] **Step 1: Write failing live-check tests** with disposable local HTTP servers for success, timeout/unreachable, authentication failure, missing conditional memory-MCP fields, and redacted diagnostics. Stub only the external socket/database boundary.
- [ ] **Step 2: Run RED:** the focused environment-config tests fail because `live` is absent.
- [ ] **Step 3: Implement bounded live probes** for configured core/MCP/provenance endpoints and the memory database, with process env overriding the selected env file.
- [ ] **Step 4: Write failing automation tests** that parse pre-commit and workflow YAML and exercise Make dry runs, asserting shared command ownership rather than duplicate inline logic.
- [ ] **Step 5: Wire Make and hooks** (`env-check`, `env-fix`, `env-live-check`; install pre-commit and pre-push) without modifying the existing Bandit block.
- [ ] **Step 6: Replace inline CI profile validation** with `make env-check`; add protected staging/prod live jobs and make promotion depend on them. Add `environment: staging|prod` so external approvals are real gates.
- [ ] **Step 7: Change only the Compose environment selector** to `ARTEMIS_ENV=${ARTEMIS_ENV:-dev}` and update the stale Docker test without touching unrelated Compose edits.
- [ ] **Step 8: Run GREEN:** focused environment, setup, automation, and Docker tests all pass.

### Task 4: Documentation, verification, and independent review

**Files:**
- Modify: `docs/ENVIRONMENTS.md`
- Modify: `.env.example` comments as needed

- [ ] **Step 1: Document ownership and commands**: policy YAML versus operator env, all setup modes, pre-commit/pre-push behavior, protected live jobs, and external GitHub approval ownership. Remove the stale CircleCI claim.
- [ ] **Step 2: Run focused verification:** `./.venv/bin/python -m pytest -q -p no:cacheprovider src/tests/test_environments.py src/tests/test_environment_config.py src/tests/test_setup_secrets.py src/tests/test_docker_compose.py`.
- [ ] **Step 3: Run source checks:** `./.venv/bin/python scripts/environment_config.py check` and `make env-check`.
- [ ] **Step 4: Run the canonical suite:** `./.venv/bin/python -m pytest -q -p no:cacheprovider src/tests`; classify any unrelated baseline failures separately.
- [ ] **Step 5: Inspect the scoped diff** for only environment-system paths and confirm unrelated dirty files are unchanged.
- [ ] **Step 6: Request independent code review** against the design spec, fix every Critical/Important finding, and rerun the covering checks before reporting completion.
