# Coding Standards Adoption Baseline

**Recorded:** 2026-08-15

**Branch:** `dev`

**Starting commit:** `b374cc801a54ffe31760b27143c6cd45b9cc974b`

## Purpose

This file separates conditions that existed before coding-standard adoption from
regressions introduced by later changes. It is evidence, not a waiver: new and
touched code follows `docs/CODING_STANDARDS.md`, and each baseline item requires a
focused repair before its gate can become repository-wide.

## Complexity and parse baseline

Command:

```bash
.venv/bin/python -m ruff check src app/api/main.py --no-cache \
  --select C901 --config 'lint.mccabe.max-complexity=20'
```

Observed findings:

| Category | Location | Baseline result |
|---|---|---|
| Complexity | `app/api/main.py:get_task_activity` | 22 |
| Complexity | `app/api/main.py:execute_instruction_stream` | 31 |
| Complexity | `src/Experiments/legal_summarization/main.py:main` | 24 |
| Complexity | `src/mcp/orchestrator.py:stream_route_and_execute` | 21 |
| Parse | `src/agents/artemis/semantic_tagging 2.py` | Invalid indentation / incomplete dedent |
| Parse | `src/core/instructions/instruction_loader.py` | Duplicated function declaration leaves an empty body |

## Enforcement decision

- Removed the standalone Radon hooks because Radon is not installed and the hooks
  silently checked nothing.
- Ruff is the selected complexity engine, consistent with the one-tool-per-concern
  standard.
- Repository-wide C901 enforcement remains pending until the four recorded
  functions are repaired or narrowly justified.
- Parse failures are higher priority than complexity cleanup and must be repaired
  before the auth and ATP implementation begins.
- No source file was reformatted or behaviorally changed while recording this
  baseline.

## Existing formatting and import baseline

The existing operator-facing checks are not green at the starting commit:

| Check | Starting result |
|---|---|
| `make lint` | Fails on the two parse-error files recorded above |
| `black --check src app` | 70 files would be reformatted; two files cannot be parsed |
| `isort --check-only src app` | 16 files report import-order drift |

These results predate this adoption change. They must not trigger a mass-format
commit. Repairs proceed in focused slices: parse correctness first, then configure
the consolidated Ruff gate, then format only files touched by an approved change.

## Reverse-sync cleanup completed in this slice

The collection blockers introduced by commit `72cf776` were repaired before the
standards baseline was handed off:

- Removed the duplicated `InstructionSet.add_scope` declaration.
- Removed the byte-identical uppercase `app/Kernel` index entries and normalized
  the physical package to canonical `app/kernel` casing.
- Removed the malformed `semantic_tagging 2.py` conflict copy while preserving
  `semantic_tagging.py`.
- Restored the Artemis package entrypoint required by `python -m src`.
- Restored the root pytest isolation guard.
- Returned the four unchanged requirement manifests to repository-root ownership.
- Removed the overbroad `*.db` ignore rule while preserving explicit runtime roots.

Validation after those repairs:

```text
pytest src/tests: 1721 passed, 2 skipped
make lint: passed
pre-commit validate-config: passed
AGENTS.md / CLAUDE.md mirror: passed
git diff --check: passed
```

The two skips require the optional `scikit-learn` experiment dependency and are
not regressions in the production routing architecture.
