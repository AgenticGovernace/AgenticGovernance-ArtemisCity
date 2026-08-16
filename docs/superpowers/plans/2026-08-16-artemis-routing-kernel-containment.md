# Artemis Reverse-Sync Containment and Release Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the reviewed reverse-sync comparison material until merge and
review completion, reduce live legacy compatibility to one facade, narrow test
and runtime authority to canonical surfaces, and make release artifacts exact
and reproducible before any later cleanup authority is reconsidered.

**Architecture:** The committed 371-path audit manifest remains the immutable
comparison source. The 217-path hold and adjacent quarantine preserve retained
legacy material without granting runtime, import, test, routing, or release
authority. Exact tracked allowlists, not broad directory includes or presence
on disk, define the releasable surface.

**Tech Stack:** Git, Python 3.12, PyYAML, pytest, Hatchling, build, twine

## Active Hold Amendment

- The historical destructive Task 3 is replaced by the committed reverse-sync
  hold until the relevant merge is complete, reviews are complete, the user
  gives fresh authorization, digests remain unchanged, and the hold/package
  gates are green.
- Task 4 is audit and quarantine only. No legacy path removal, restore, move,
  rename, or rewrite is permitted while the hold is active.
- Task 5 may migrate unique root-test behavior and narrow default collection to
  `src/tests`, but it must retain the root test tree while the hold is active.
- Task 6 must exclude held and quarantined material through exact tracked
  allowlists even while those files remain present in the repository.
- Historical destructive checkboxes below are suspended while the hold is
  active and cannot be executed from this plan without a superseding amendment.

**Spec:** `docs/superpowers/specs/2026-08-16-artemis-routing-kernel-consolidation-design.md`

## Global Constraints

- Work only on `feature/routing-kernel-consolidation`; do not reset, clean, rebase, or overwrite the shared dirty worktree.
- The source manifest is `docs/audits/2026-08-16-reverse-sync-72cf776-path-manifest.yaml` at SHA-256 `60d558d7d4f2881fed87a15d61b4ad018892aba8f2690d91f172b5be3b94914e`.
- The manifest's exact 371-path source delta remains partitioned as 21 `KEEP_AUTHORITATIVE`, 1 `KEEP_COMPATIBILITY`, 221 `REMOVE_REVERSE_SYNC`, 79 `REVIEW_SEPARATELY`, and 49 `ALREADY_CORRECTED`.
- Do not revert commit `72cf776` wholesale. Apply only manifest-authorized path actions.
- Preserve all 79 `REVIEW_SEPARATELY` paths byte-for-byte during the deterministic slice.
- Before removing any adjacent path, add its path, classification, rationale, and evidence to `adjacent_current_tree_findings` and verify adjacent entries remain excluded from the 371-path counts.
- Tracked removals are recoverable from Git. Do not delete untracked notebooks, vault records, figures, logs, databases, or user artifacts as part of this plan.
- `src/Kernel/__init__.py` is the only runtime-compatible `src.Kernel` path. It must re-export the canonical `app.kernel` identity rather than define a second class.
- `src/tests` is the sole Python test authority after unique root-test behavior is migrated.
- Wheel and sdist payloads contain only committed approved files; untracked and locally excluded content can never enter a release artifact.
- New and touched code follows `docs/CODING_STANDARDS.md`; do not mass-format unrelated files.
- Stage and commit only the paths named by each task.

---

### Task 1: Land the already reviewed canonical-layout corrections

**Files:**
- Delete: `app/Kernel/__init__.py`
- Delete: `app/Kernel/agent_router.py`
- Delete: `app/Kernel/agent_router.yaml`
- Delete: `app/Kernel/agents/__init__.py`
- Delete: `app/Kernel/agents/base.py`
- Delete: `app/Kernel/agents/daemon_agent.py`
- Delete: `app/Kernel/agents/planner_agent.py`
- Delete: `app/Kernel/artemis_cli.py`
- Delete: `app/Kernel/cli.py`
- Delete: `app/Kernel/kernel.py`
- Delete: `app/Kernel/memory_bus.py`
- Move: `app/requirements.txt` to `requirements.txt`
- Move: `app/requirements-dev.txt` to `requirements-dev.txt`
- Move: `app/requirements-docker.txt` to `requirements-docker.txt`
- Move: `app/requirements-runtime.txt` to `requirements-runtime.txt`
- Delete: `src/agents/artemis/semantic_tagging 2.py`
- Modify: `src/__init__.py`
- Create: `conftest.py`

**Interfaces:**
- Consumes: the exact currently staged layout correction.
- Produces: one case-normalized `app/kernel`, root dependency manifests, and a root pytest safety boundary.

- [ ] **Step 1: Confirm the staged set is exact before committing**

  Run:

  ```bash
  git diff --cached --name-status
  ```

  Expected: only the 11 `app/Kernel` deletions, four 100% requirements renames,
  and `src/agents/artemis/semantic_tagging 2.py` deletion are staged. If any
  other path appears, stop and unstage only the unexpected path; never reset the
  worktree.

- [ ] **Step 2: Verify the corrected lower-case runtime and safety fixture**

  Run:

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_cli_entrypoints.py \
    src/tests/test_coverage_foundations.py \
    src/tests/test_setup_secrets.py
  cmp AGENTS.md CLAUDE.md
  git diff --check -- src/__init__.py conftest.py
  ```

  Expected: focused tests pass, guidance mirrors match, and whitespace is clean.
  Record any pre-existing failure separately; do not weaken the tests.

- [ ] **Step 3: Stage only the two corrected support files**

  ```bash
  git add src/__init__.py conftest.py
  git diff --cached --name-status
  ```

  Expected: the staged set is exactly the files named in this task.

- [ ] **Step 4: Commit the canonical layout correction**

  ```bash
  git commit -m "chore: restore canonical repository layout"
  ```

---

### Task 2: Add executable reverse-sync and repository-boundary gates

**Files:**
- Create: `src/tests/test_reverse_sync_cleanup.py`
- Create: `src/tests/test_repository_boundaries.py`
- Create: `src/tests/test_release_artifacts.py`
- Modify: `src/tests/test_makefile_contract.py`

**Interfaces:**
- Consumes: the committed audit manifest and Git index.
- Produces: `load_reverse_sync_manifest()`, exact classification assertions, case-fold checks, runtime-identity checks, and artifact payload checks.

- [ ] **Step 1: Write the manifest integrity test**

  Parse with `yaml.safe_load`, expand each rename into source `D` and destination
  `A`, and compare exact `(path, status)` pairs with:

  ```bash
  git diff-tree --no-commit-id --name-status -r -M \
    72cf776a69b260d4bcc2c811179d49dc34dbbf0d
  ```

  The test asserts the literal counts and source hash:

  ```python
  assert expanded_status_counts == {"A": 293, "M": 18, "D": 60}
  assert classification_counts == {
      "KEEP_AUTHORITATIVE": 21,
      "KEEP_COMPATIBILITY": 1,
      "REMOVE_REVERSE_SYNC": 221,
      "REVIEW_SEPARATELY": 79,
      "ALREADY_CORRECTED": 49,
  }
  assert len(expanded_paths) == len(set(expanded_paths)) == 371
  assert manifest_sha256 == (
      "60d558d7d4f2881fed87a15d61b4ad018892aba8f2690d91f172b5be3b94914e"
  )
  ```

- [ ] **Step 2: Write repository-boundary tests before cleanup**

  Add failing assertions that:

  - no two tracked paths collide under `casefold()`;
  - `src/Kernel` exposes only `__init__.py` as importable Python;
  - `src.Kernel.Kernel is app.kernel.Kernel`;
  - production `src/` and `app/` modules do not import `artemis_mcp_common`;
  - no runtime registry, output, CLI prompt, or package path contains a
    case-insensitive Codex identity;
  - `pyproject.toml` declares only `src/tests` in `testpaths` after Task 5.

- [ ] **Step 3: Write artifact tests before narrowing packaging**

  Build wheel and sdist into a temporary directory. Reject paths matching this
  closed rule set:

  ```python
  FORBIDDEN_PARTS = {
      "__pycache__",
      "node_modules",
      "memory_store",
      "obsidian_vault",
      ".pytest_cache",
      ".mypy_cache",
      ".ruff_cache",
  }
  FORBIDDEN_SUFFIXES = {
      ".db",
      ".sqlite",
      ".sqlite3",
      ".log",
      ".wav",
      ".zip",
      ".ipynb",
      ".pyc",
  }
  ```

  Also reject tests, `src/Kernel/**` beyond `__init__.py`, case-fold
  collisions, `* 2.*`, `* copy.*`, prior `dist/`, and every artifact member
  absent from the committed allowlist files introduced in Task 6.

- [ ] **Step 4: Run the new tests and verify meaningful RED**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_reverse_sync_cleanup.py \
    src/tests/test_repository_boundaries.py \
    src/tests/test_release_artifacts.py \
    src/tests/test_makefile_contract.py
  ```

  Expected: the manifest-integrity portion passes; legacy duplicate, test-root,
  and broad-artifact assertions fail against the current tree.

- [ ] **Step 5: Commit the failing boundary characterization**

  ```bash
  git add src/tests/test_reverse_sync_cleanup.py \
    src/tests/test_repository_boundaries.py \
    src/tests/test_release_artifacts.py src/tests/test_makefile_contract.py
  git commit -m "test: lock repository cleanup boundaries"
  ```

---

### Task 3: Apply the deterministic 371-path manifest slice

**Files:**
- Delete: the exact 217 manifest `paths` entries with `classification=REMOVE_REVERSE_SYNC` and `source_status=A`.
- Restore from `613abc0`: `.devcontainer/devcontainer.json`
- Restore from `613abc0`: `.github/workflows/promote.yml`
- Restore from `613abc0`: `.vscode/settings.json`
- Restore from `613abc0`: `app/web/frontend/.env.example`
- Restore from `613abc0`: `benchmarks/bench_memory_ops.py`
- Restore from `613abc0`: `examples/README.md`
- Restore from `613abc0`: `examples/governance_demo/README.md`
- Restore from `613abc0`: `examples/governance_demo/run.py`
- Restore from `613abc0`: `examples/minimal_deployment/README.md`
- Restore from `613abc0`: `examples/minimal_deployment/run.py`
- Restore from `613abc0`: `examples/multi_agent_workflow/README.md`
- Restore from `613abc0`: `examples/multi_agent_workflow/run.py`
- Restore from `613abc0`: `sandbox_city/_Index_of_sandbox_city.md`
- Restore from `613abc0`: `sandbox_city/index.md`
- Restore from `613abc0`: `sandbox_city/semantic_zones.md`
- Restore from `613abc0`: `app/scripts/data/vector_store.db`
- Restore from `613abc0`: `supabase/migrations/artemis.sql`
- Restore from `613abc0`: `monitoring/alerts.yml`
- Restore from `613abc0`: `monitoring/prometheus.yml`
- Preserve: `src/exceptions.py`
- Preserve unchanged: all 79 `REVIEW_SEPARATELY` paths.

**Interfaces:**
- Consumes: verified manifest and parent `613abc0` canonical blobs.
- Produces: the deterministic cleanup slice only; mixed paths remain for later review.

- [ ] **Step 1: Materialize and validate the exact removal list**

  Use a temporary NUL-delimited file generated from parsed YAML. Before any
  deletion, assert all of the following in one foreground check:

  - SHA-256 matches the approved literal;
  - selected count is exactly 217;
  - every selected path is a tracked regular file beneath the repository root;
  - no selected path is a symlink or contains `..`;
  - every selected entry is `source_status=A` and
    `classification=REMOVE_REVERSE_SYNC`;
  - none is in `REVIEW_SEPARATELY`.

  Print the full selected path list and inspect it before proceeding.

- [ ] **Step 2: Dry-run the tracked removals**

  ```bash
  git rm -n --pathspec-from-file=/private/tmp/artemis-reverse-sync-remove.nul \
    --pathspec-file-nul
  ```

  Expected: exactly 217 tracked paths, identical to Step 1. If any path differs,
  stop; do not broaden the selection.

- [ ] **Step 3: Remove the exact tracked paths**

  ```bash
  git rm --pathspec-from-file=/private/tmp/artemis-reverse-sync-remove.nul \
    --pathspec-file-nul
  ```

- [ ] **Step 4: Restore the exact 19 canonical blobs**

  Use `git restore --source=613abc0 --staged --worktree --` followed by the 19
  explicit paths named in this task. Do not use a directory glob or restore any
  other path.

- [ ] **Step 5: Prove mixed paths and compatibility stayed untouched**

  Compare SHA-256 for all 79 `REVIEW_SEPARATELY` paths against the pre-task
  snapshot. Assert `src/exceptions.py` is present and byte-identical to the
  pre-task file.

- [ ] **Step 6: Run focused verification and commit**

  ```bash
  .venv/bin/python -m pytest src/tests/test_reverse_sync_cleanup.py -q
  git diff --check
  git add -u \
    --pathspec-from-file=/private/tmp/artemis-reverse-sync-remove.nul \
    --pathspec-file-nul
  git add .devcontainer/devcontainer.json .github/workflows/promote.yml \
    .vscode/settings.json app/web/frontend/.env.example benchmarks \
    examples sandbox_city app/scripts/data/vector_store.db \
    supabase/migrations/artemis.sql monitoring
  git commit -m "chore: apply reviewed reverse-sync cleanup"
  ```

---

### Task 4: Reduce legacy `src.Kernel` to one compatibility facade

**Files:**
- Modify: `docs/audits/2026-08-16-reverse-sync-72cf776-path-manifest.yaml`
- Modify: `src/Kernel/__init__.py`
- Delete after classification: all tracked Python, YAML, JSON, and runtime-store paths under `src/Kernel/**` except `src/Kernel/__init__.py`.
- Preserve for separate retention review: `src/Kernel/Kernel.md`, `src/Kernel/agents/agents.md`, and `src/Kernel/memory_store/memory_store.md`.
- Delete: `src/integration/state_kernel.json`
- Delete: `src/tests/integration/test_artemis_persona 2.py`
- Delete: `tests/integration/test_artemis_persona 2.py`
- Create: `services/mcp/common/README.md`
- Modify: `src/tests/test_repository_boundaries.py`
- Modify: `src/tests/test_coverage_foundations.py`

**Interfaces:**
- Consumes: canonical `app.kernel.Kernel` and the manifest's adjacent-evidence section.
- Produces: one identity-preserving compatibility import and an explicit MCP-incubator quarantine.

- [ ] **Step 1: Complete adjacent classifications before deleting**

  Enumerate `git ls-files 'src/Kernel/**'` and require exactly one Python path to
  remain: `src/Kernel/__init__.py`. Add every not-yet-recorded code/runtime path
  to `adjacent_current_tree_findings` with one of these evidence-backed reasons:

  - byte-identical lower-case duplicate;
  - broken Codex-era runtime identity;
  - generated task/memory/state artifact;
  - unreferenced legacy agent implementation.

  Keep the three Markdown histories listed above classified for separate
  retention review and excluded from release artifacts. Re-run the manifest
  integrity test and verify the original 371-path counts are unchanged.

- [ ] **Step 2: Write the compatibility identity test**

  ```python
  def test_uppercase_kernel_is_only_an_identity_facade():
      from app.kernel import Kernel as CanonicalKernel
      from src.Kernel import Kernel as CompatibilityKernel

      assert CompatibilityKernel is CanonicalKernel
  ```

  Add a filesystem assertion that no other `*.py` file exists beneath
  `src/Kernel`.

- [ ] **Step 3: Implement the sole compatibility initializer**

  `src/Kernel/__init__.py` contains only a deprecation docstring, the canonical
  import, and `__all__`:

  ```python
  """Deprecated case-sensitive facade for :mod:`app.kernel`."""

  from app.kernel import Kernel

  __all__ = ["Kernel"]
  ```

- [ ] **Step 4: Remove classified legacy code and runtime artifacts**

  Enumerate the exact tracked targets from the updated adjacent manifest,
  verify each is beneath `src/Kernel`, print them, dry-run `git rm`, and then
  remove only those paths. Remove the two duplicate persona tests and
  `src/integration/state_kernel.json` by their explicit paths. Do not delete the
  three Markdown histories in this task.

- [ ] **Step 5: Quarantine dormant MCP authority scaffolding**

  `services/mcp/common/README.md` must state:

  - the package is an incubator and not a production authentication,
    authorization, routing, or principal authority;
  - `GovernedGate` is unsafe to wire because capability is not derived from ATP;
  - production modules must not import it;
  - the governed-core plan will replace its gate/principal types with adapters.

- [ ] **Step 6: Run boundary tests and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_reverse_sync_cleanup.py \
    src/tests/test_repository_boundaries.py \
    src/tests/test_coverage_foundations.py
  git add docs/audits/2026-08-16-reverse-sync-72cf776-path-manifest.yaml \
    src/Kernel services/mcp/common/README.md \
    src/integration/state_kernel.json \
    'src/tests/integration/test_artemis_persona 2.py' \
    'tests/integration/test_artemis_persona 2.py'
  git commit -m "refactor: reduce legacy kernel to compatibility facade"
  ```

---

### Task 5: Make `src/tests` the sole Python test authority

**Files:**
- Create: `docs/audits/2026-08-16-root-test-tree-disposition.yaml`
- Modify: `src/tests/integration/test_governance.py`
- Modify: `src/tests/integration/test_hebbian_sync.py`
- Modify: `src/tests/integration/test_memory_decay.py`
- Modify: `src/tests/integration/test_sandbox.py`
- Modify: `src/tests/test_llm_agent.py`
- Delete after migration: all 64 tracked paths under `tests/**`.
- Modify: `pyproject.toml`
- Preserve: repository-root `conftest.py`.

**Interfaces:**
- Consumes: two currently collected test trees and their AST/test-node inventory.
- Produces: one disposition record and one canonical collection root with no lost unique behavior.

- [ ] **Step 1: Record exact root-test dispositions**

  Compare AST test function/class names and parametrization between `tests/`
  and `src/tests/`. The disposition YAML records every tracked root test as
  `duplicate`, `migrate`, or `obsolete`, with destination and evidence. The
  current audit baseline is 76 root-only cases:

  - 21 to `src/tests/integration/test_governance.py`;
  - 24 to `src/tests/integration/test_hebbian_sync.py`;
  - 14 to `src/tests/integration/test_memory_decay.py`;
  - 15 to `src/tests/integration/test_sandbox.py`;
  - 2 to `src/tests/test_llm_agent.py`.

  If live counts differ, stop and update the audit from the current tree before
  deleting anything.

- [ ] **Step 2: Copy unique test behavior into canonical modules**

  Preserve literal assertions and fixtures. Do not copy imports or fixture code
  that points back to `tests/`. Run each destination module immediately after
  migration:

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/integration/test_governance.py \
    src/tests/integration/test_hebbian_sync.py \
    src/tests/integration/test_memory_decay.py \
    src/tests/integration/test_sandbox.py \
    src/tests/test_llm_agent.py
  ```

- [ ] **Step 3: Delete the audited root tree and narrow discovery**

  Confirm the disposition manifest covers all 64 tracked `tests/**` paths,
  dry-run their deletion, then remove exactly those tracked paths. Change:

  ```toml
  [tool.pytest.ini_options]
  testpaths = ["src/tests"]
  python_files = ["test_*.py"]
  addopts = "-ra"
  ```

- [ ] **Step 4: Prove default and explicit collection match**

  ```bash
  .venv/bin/python -m pytest --collect-only -q -p no:cacheprovider
  .venv/bin/python -m pytest --collect-only -q -p no:cacheprovider src/tests
  make test
  ```

  Expected: the two collection node sets are identical and canonical tests pass.

- [ ] **Step 5: Commit canonical test discovery**

  ```bash
  git add docs/audits/2026-08-16-root-test-tree-disposition.yaml \
    src/tests pyproject.toml
  git add -u tests
  git commit -m "test: make src tests the sole collection root"
  ```

---

### Task 6: Enforce explicit tracked wheel and sdist allowlists

**Files:**
- Create: `config/release/python-wheel-files.v1.txt`
- Create: `config/release/python-sdist-files.v1.txt`
- Modify: `pyproject.toml`
- Modify: `src/tests/test_release_artifacts.py`
- Modify: `src/tests/test_makefile_contract.py`
- Modify: `Makefile`
- Modify: `.circleci/config.yml`

**Interfaces:**
- Consumes: the cleaned tracked tree and one canonical test root.
- Produces: exact release payload manifests, `make package-check`, and an isolated-wheel import proof.

- [ ] **Step 1: Generate and review tracked allowlist candidates**

  The wheel candidate contains only approved runtime Python and required package
  data from maintained `src` packages, `src/Kernel/__init__.py`,
  `app/__init__.py`, and `app/kernel/**`. The sdist candidate adds only approved
  build metadata, operator docs, source tests, configuration, and migrations.
  Both lists are UTF-8, sorted bytewise, one relative POSIX path per line, with
  no glob syntax.

  Reject candidate members that are untracked, ignored, case-colliding,
  copy-suffixed, or match the forbidden rules from Task 2.

- [ ] **Step 2: Narrow Hatch build inputs**

  Replace the broad `only-include = ["src", "app"]` rule with explicit runtime
  package includes and add an explicit sdist include/exclude section. Keep
  `app/api`, `app/web`, `app/scripts`, tests, services incubators, experiments,
  vaults, data, logs, caches, and previous builds outside the wheel.

- [ ] **Step 3: Make artifact tests compare exact members**

  Build into a fresh temporary directory. Normalize wheel `.dist-info` metadata
  as the small versioned metadata allowance; every other wheel/sdist member must
  equal the corresponding committed allowlist. Assert every payload source is
  returned by `git ls-files`.

- [ ] **Step 4: Add one operator and CI gate**

  `make package-check` performs, in order:

  ```bash
  python -m build
  python -m twine check dist/*
  python -m pytest -q src/tests/test_release_artifacts.py \
    src/tests/test_repository_boundaries.py
  ```

  CircleCI invokes `make package-check`; it does not duplicate the logic.

- [ ] **Step 5: Install and inspect the real wheel**

  Create a fresh temporary virtual environment, install the wheel with
  `--no-deps`, and assert:

  ```python
  import app.kernel
  import src
  import src.Kernel

  assert src.Kernel.Kernel is app.kernel.Kernel
  ```

  Inspect both archives for forbidden paths and case-fold collisions.

- [ ] **Step 6: Run release proof and commit**

  ```bash
  .venv/bin/python -m pytest -q \
    src/tests/test_release_artifacts.py \
    src/tests/test_repository_boundaries.py \
    src/tests/test_makefile_contract.py
  make package-check
  make test
  git add config/release pyproject.toml src/tests/test_release_artifacts.py \
    src/tests/test_makefile_contract.py Makefile .circleci/config.yml
  git commit -m "build: enforce tracked release allowlists"
  ```
