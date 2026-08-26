# Environment Contract and Provisioning Design

## Goal

Make `config/environments/` the sole committed environment-policy source,
make the ignored root `.env` the local operator-value source, and make one
root command provision and verify every maintained runtime without inventing
operator credentials or deployment endpoints.

## Ownership model

- `config/environments/{dev,staging,prod}.yaml` contains policy only. It must
  never contain credentials, database URLs, service endpoints, model choices,
  or machine-local paths.
- `.env.example` is the complete, non-secret variable inventory. Missing
  variables are detected from maintained runtime source, so the template is
  not assumed to be complete merely because it exists.
- The ignored root `.env` is the local operator source. Service `.env` files
  are generated views containing only the keys declared by their templates.
- The provisioner owns generation and rotation only for
  `MCP_API_KEY`, `FASTAPI_API_KEY`, `ARTEMIS_API_KEY_DEFAULT`,
  `REDIS_PASSWORD`, `QDRANT_API_KEY`, and `GRAFANA_PASSWORD`.
  `ARTEMIS_VECTOR_STORE_API_KEY` is derived from `QDRANT_API_KEY`.
- All other secrets, endpoints, database URLs, identities, model selections,
  and Authstructure fields are operator-owned. Setup may add their blank or
  safe-default declarations but must never fabricate their real values.
- `.github/environments/` contains frozen historical artifacts protected by
  the active reverse-sync hold. They are never loaded or validated as runtime
  policy. The canonical files are under `config/environments/` only.

## Profile contract

Every profile has exactly this public shape; `load_environment()` continues
to return a dictionary for compatibility:

```yaml
schema_version: 1
name: dev
description: Local and shared developer integration environment.
runtime:
  log_level: TRACE
  debug: true
  reload: true
governance:
  strict_atp: true
  trust_default_level: 2
deploy:
  branch: dev
  github_environment: dev
```

`name`, `deploy.branch`, and `deploy.github_environment` must equal the file
stem. `log_level` is one of `TRACE`, `DEBUG`, `INFO`, `WARN`, or `ERROR`;
booleans must be YAML booleans; trust level is an integer from 0 through 3.
Approval counts are not stored in YAML: required reviewers and wait timers are
owned by GitHub Environment settings.

Canonical policy values are:

| Profile | Log level | Debug | Reload | Trust |
|---|---:|---:|---:|---:|
| `dev` | `TRACE` | true | true | 2 |
| `staging` | `INFO` | false | false | 1 |
| `prod` | `WARN` | false | false | 1 |

## Commands and behavior

`scripts/environment_config.py` is the implementation entrypoint:

```text
environment_config.py check
environment_config.py fix
environment_config.py setup [--check | --regenerate]
environment_config.py live
```

- `check` is read-only and validates profiles, unique template keys,
  root-template superset coverage, code-discovered variables, and contract
  targets. Separate repository tests pin hook and CI wiring.
- `fix` only rewrites the three tracked canonical policy profiles from the
  reviewed defaults and stable schema. It never reads or writes `.env` files.
- `setup` preserves the existing `setup_secrets.sh` CLI behavior while parsing
  `.env` files in Python. It reconciles every contract target, generates only
  owned secrets, preserves operator values, makes files mode `0600`, and uses
  root values for matching keys in generated service views.
- `live` loads the ignored root `.env` plus process overrides and probes every
  manifest-declared configured service.
  It reports variable and service names but never values, tokens, URLs with
  credentials, or database connection strings. HTTP probes use bounded
  timeouts; database validation runs `SELECT 1` when the memory MCP service is
  configured.
- `setup_secrets.sh` remains the user-facing compatible wrapper and adds
  `--live` as a direct alias for the live checker.

Maintained targets are root/core, FastAPI/Express, the standalone Obsidian
memory layer, `services/mcp/artemis-memory`, and `services/prove`.
`artemis-validation` has no environment inputs and therefore has no generated
env file.

## Automation

- `make env-fix` runs deterministic tracked-source repair.
- `make env-check` is read-only and runs on every commit and pull request.
- `make env-live-check` loads the ignored root `.env` locally.
- Pre-commit runs `env-fix`; pre-push runs `env-live-check`. Hook installation
  installs both stages.
- Pull-request CI runs only `env-check`, because forked PRs cannot access
  deployment secrets.
- Staging and production promotion each enter the corresponding protected
  GitHub Environment and run `env-live-check` using environment-scoped vars
  and secrets before the branch pointer advances.
- Docker Compose uses `${ARTEMIS_ENV:-dev}` rather than an invalid
  `production` value or a hard-coded `dev` value.

## Compatibility and safety

- Existing ordinary values and operator credentials survive sync and
  regeneration. Owned-secret regeneration changes only the explicit owned
  set and its derived alias.
- Explicit environment names are normalized and validated before path
  construction, preventing traversal and inconsistent `production` aliases.
- No hook writes populated `.env` files. Only the explicit setup command does.
- The current dirty checkout is preserved: no unrelated file is staged,
  reverted, deleted, or committed.
