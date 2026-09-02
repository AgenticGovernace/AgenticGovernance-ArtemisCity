# Project Boundaries

This repository currently contains several projects that share one git tree.
This document is the working separation map: it identifies each project,
records how it is run, and names the next safe step for splitting it without
breaking the Artemis City core.

For the responsibility, data, and test boundaries _inside_ these projects, use
[`REPOSITORY_LAYERS.md`](REPOSITORY_LAYERS.md).

## Active Projects

| Project                           | Current path        | Runtime                                             | Manifest or entry point                                             | Status                         | Separation target                                                                                                  |
| --------------------------------- | ------------------- | --------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| Artemis Python core               | `src/`              | Python 3.12                                         | `pyproject.toml`, `requirements.txt`, `src/mcp/orchestrator.py`     | Active authoritative core      | Root `pyproject.toml` is canonical                                                                                 |
| In-process kernel                 | `app/kernel/`       | Python 3.12                                         | `app/kernel/cli.py`, `app/kernel/kernel.py`                         | Active, packaged with the core | Keep with the Python core package                                                                                  |
| FastAPI dashboard backend         | `app/api/main.py`   | Python/FastAPI                                      | `make api`, `app/api/main.py`                                       | Active dashboard surface       | Split into `services/dashboard-api/` after imports are stable                                                      |
| TypeScript Express API            | `app/api/**/*.ts`   | Node/TypeScript/Express                             | `app/api/package.json`, `app/api/tsconfig.json`, `app/api/index.ts` | Active public HTTP boundary    | Ready for a later physical move to `services/express-api/`                                                         |
| React dashboard frontend          | `app/web/frontend/` | Node/TypeScript/React/Vite                          | `app/web/frontend/package.json`, `vite.config.ts`                   | Active frontend                | Split into `apps/dashboard-web/`                                                                                   |
| Launch demos and CLI walkthroughs | `src/launch/`       | Python scripts, feature-only npm compatibility shim | `src/launch/Makefile`, `src/launch/package.json`                    | Transitional                   | Keep scripts near the core; the shim delegates to the Makefile and can be retired in a separately approved cleanup |
| Static concept demos              | `Concept_Demos/`    | Static HTML/browser demos                           | `Concept_Demos/README.md`                                           | Supported prototype gallery    | Split into `examples/concept-demos/` or keep as non-package docs assets                                            |

## Incomplete Or Stale Project Shells

| Surface                              | Current path                        | Evidence                                                                                                                                                                                                                                                                                | Recommended action                                                                                   |
| ------------------------------------ | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Obsidian REST shell                  | `app/Artemis Agentic Memory Layer/` | Working `package.json`, `Dockerfile`, and `middleware/auth.ts` are present; `make server` runs it. Not registered in the root npm workspace. Branding-only — plain REST, no `@modelcontextprotocol/sdk` dependency; the reviewed MCP design does not treat it as Model Context Protocol | Register it in the root npm workspace before treating it as a production dependency                  |
| Legacy web API copy                  | `archive/legacy-web-api/`           | Old `../app/web/backend` FastAPI copies; active dashboard API is `app/api/main.py`                                                                                                                                                                                                            | Archived for reference                                                                               |
| Duplicate memory integration package | `memory/`                           | Mirrors `src/memory/` names outside the package root                                                                                                                                                                                                                                    | Verify imports, then remove or convert to compatibility shims                                        |
| Duplicate root tests                 | `tests/`                            | Substantially overlaps `src/tests/`, but is not byte-identical                                                                                                                                                                                                                          | Keep `src/tests/` canonical; root `tests/` is migration-only and documented by `tests/README.md`     |
| Historical kernel placeholder        | `src/Kernel/`                       | Only `__init__.py`; maintained kernel is `app/kernel/`                                                                                                                                                                                                                                  | Remove once import search confirms it is unused                                                      |
| Local GitHub Actions runner          | `actions-runner/`                   | Runtime tool directory, not source code                                                                                                                                                                                                                                                 | Move outside the repository or add to ignore rules after confirming it is not intentionally vendored |
| Marketplace prototype                | `quantum-harmony-marketplace/`      | Separate top-level product-like directory                                                                                                                                                                                                                                               | Inspect manifest/docs, then split or archive independently                                           |
| Simulation sandbox                   | `sandbox_city/`                     | Legacy city simulation assets referenced by archived docs and old launch package scripts                                                                                                                                                                                                | Keep as examples only or move under `examples/sandbox-city/`                                         |

## Cross-Project Coupling To Preserve

- The TypeScript Express API must call Python through `app/api/lib/pythonBridge.ts`
  and `src/api_bridge.py`; it should not import or reimplement Python logic.
- The React frontend talks to the FastAPI dashboard on `/api/*`, not the
  Express `/api/v1/*` boundary.
- The Python wheel is intended to include `src/` and `app/kernel/`, while
  excluding `app/api`, `app/web`, and `app/scripts`.
- Environment files are coordinated by `setup_secrets.sh`; splitting projects
  should preserve the existing `.env`, `app/api/.env`, and `src/.env` flow.

## Current Hygiene State

These must be resolved before broad file moves or package extraction:

1. No `<<<<<<<` or `>>>>>>>` merge-conflict markers are currently present.
2. Root `pyproject.toml` is the canonical Python package manifest.
3. Package-lock files parse as JSON. The Express API now has a local manifest,
   local TypeScript config, and regenerated local lockfile.
4. `app/Artemis Agentic Memory Layer/` is a runnable standalone Obsidian REST
   shell, but is not a registered workspace service, and is not a Model
   Context Protocol implementation despite its name — the real MCP SDK is
   used under `services/mcp/`.
5. `AGENTS.md` and `CLAUDE.md` are currently byte-for-byte mirrors and must
   remain mirrored whenever
   either is edited.

## Separation Sequence

1. Keep `app/web/frontend/` as the frontend package; remove server/controller
   leftovers from that tree once confirmed unused.
2. Compare duplicate tests and memory packages; move canonical tests under
   `src/tests/` and archive or delete duplicates.
3. Rebuild or archive the historical Obsidian MCP server directory and classify
   the two imported REST-shell copies before registering any server package.
4. Move legacy demos and sandboxes under `examples/` after active runtimes pass
   tests.

## Completed Separation Steps

- Added a local Express API manifest and TypeScript config under `app/api/`.
- Regenerated `app/api/package-lock.json` from the local Express API manifest.
- Converted the root `package.json` into a workspace coordinator instead of an
  Express API service manifest.
- Registered `app/api` and `app/web/frontend` as npm workspaces.
- Aligned the frontend Vite version with `@vitejs/plugin-react`'s peer range so
  the workspace resolves without forced peer-dependency overrides.
- Verified `npm run typecheck` from the root, which delegates to both the
  Express API and React frontend typechecks.
- Promoted root `pyproject.toml` to the canonical Python package manifest.
- Verified the Python wheel build from the root manifest with
  `uv run --with build --with hatchling python -m build --wheel --no-isolation`.
- Moved the obsolete `../app/web/backend` FastAPI copy into
  `archive/legacy-web-api/`.
