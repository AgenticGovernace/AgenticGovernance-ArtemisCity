# Coding Standards Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one concise, enforceable Artemis City coding standard without mass-changing established code.

**Architecture:** The repository-owned standard defines hard safety invariants separately from review guidance and experimental practices. Existing build tools are aligned incrementally: documentation and stale paths first, then overlapping tools are consolidated only after a baseline run proves the replacement gate covers the same behavior.

**Tech Stack:** Markdown, Make, pre-commit, Black, Ruff, mypy, ESLint, pytest, Bandit

**Spec:** `docs/CODING_STANDARDS.md`

## Global Constraints

- Apply new rules to new and touched code; do not mass-format the repository.
- Keep Black's existing line length of 88 characters.
- Preserve `AGENTS.md` and `CLAUDE.md` as byte-identical mirrors.
- Security, ATP, authorization, and required provenance paths fail closed.
- Transport adapters must not duplicate domain, memory, or provenance logic.
- Notebooks and generated artifacts are outside the production lint/type gate.
- No new runtime dependency is introduced by this plan.

---

### Task 1: Establish the canonical standard

**Files:**
- Create: `docs/CODING_STANDARDS.md`
- Create: `docs/superpowers/plans/2026-08-15-coding-standards-adoption.md`

**Interfaces:**
- Consumes: `/Users/pucci/Documents/CODING_STANDARDS.md` as proposal/reference material.
- Produces: the repository-owned policy referenced by project guidance and quality gates.

- [x] **Step 1: Add the corrected repository standard**

  Define scope, hard safety invariants, Python and TypeScript practices, experiment boundaries, one-tool-per-concern policy, and incremental adoption.

- [x] **Step 2: Verify the standard contains the load-bearing rules**

  Run:

  ```bash
  grep -nE "fail closed|Mode.*ActionType|SEED|88 characters|touched code" docs/CODING_STANDARDS.md
  ```

  Expected: every expression is present at least once.

- [x] **Step 3: Check Markdown whitespace**

  Run:

  ```bash
  git diff --check -- docs/CODING_STANDARDS.md docs/superpowers/plans/2026-08-15-coding-standards-adoption.md
  ```

  Expected: no output and exit status 0.

### Task 2: Connect the project guidance

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `.github/instructions/instructions.md`

**Interfaces:**
- Consumes: `docs/CODING_STANDARDS.md`.
- Produces: one discoverable coding-policy pointer in every active guidance surface.

- [x] **Step 1: Add the source-of-truth pointer**

  Add the same coding-standard sentence to the active Source of Truth section in all three guidance files. Do not copy the whole standard into those files.

- [x] **Step 2: Verify the mirrors remain identical**

  Run:

  ```bash
  cmp AGENTS.md CLAUDE.md
  ```

  Expected: no output and exit status 0.

- [x] **Step 3: Verify all references resolve**

  Run:

  ```bash
  grep -n "docs/CODING_STANDARDS.md" AGENTS.md CLAUDE.md .github/instructions/instructions.md
  ```

  Expected: one active reference in each file.

### Task 3: Remove dead complexity enforcement and record the baseline

**Files:**
- Modify: `.pre-commit-config.yaml`
- Create: `docs/CODING_STANDARDS_BASELINE.md`

**Interfaces:**
- Consumes: current production paths `src/` and `app/api/main.py`.
- Produces: an explicit Ruff baseline and removal of Radon hooks that silently checked nothing because Radon is not installed.

- [x] **Step 1: Prove the old hook is unavailable**

  Run `.venv/bin/python -m radon --version` and record the missing-module result.

- [x] **Step 2: Run Ruff at the same hard threshold**

  Run:

  ```bash
  .venv/bin/python -m ruff check src app/api/main.py --no-cache \
    --select C901 --config 'lint.mccabe.max-complexity=20'
  ```

  Expected: current complexity and parse failures are recorded in `docs/CODING_STANDARDS_BASELINE.md` rather than hidden.

- [x] **Step 3: Remove the dead Radon hooks**

  Delete the Radon complexity and informational function-size hooks. Ruff becomes the selected complexity engine after baseline cleanup.

- [x] **Step 4: Validate pre-commit configuration syntax**

  Run:

  ```bash
  .venv/bin/python -m pre_commit validate-config .pre-commit-config.yaml
  ```

  Expected: exit status 0.

### Task 4: Establish the consolidation baseline

**Files:**
- Inspect: `Makefile`
- Inspect: `.pre-commit-config.yaml`
- Inspect: `pyproject.toml`
- Inspect: `eslint.config.js`

**Interfaces:**
- Consumes: existing Black, isort, Flake8, Ruff, mypy, ESLint, pytest, and Bandit configuration.
- Produces: evidence for a later tool-consolidation change; no tool is removed without equivalent coverage.

- [x] **Step 1: Run the current focused quality commands**

  Run:

  ```bash
  make lint
  .venv/bin/python -m black --check src app
  .venv/bin/python -m isort --check-only src app
  ```

  Expected: results are captured separately so pre-existing failures are distinguishable from regressions.

- [x] **Step 2: Validate only the files changed by this plan**

  Run:

  ```bash
  git diff --check
  cmp AGENTS.md CLAUDE.md
  .venv/bin/python -m pre_commit validate-config .pre-commit-config.yaml
  ```

  Expected: all three commands pass.

- [x] **Step 3: Defer overlapping-tool removal to its own reviewed change**

  Preserve the baseline output. A later change may replace isort, Flake8, Pylint, and standalone Radon checks with Ruff only after Ruff is configured and shown to cover the selected import, correctness, complexity, and simplification rules.
