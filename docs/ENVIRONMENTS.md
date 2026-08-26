# Environment ownership and promotion

Artemis City uses three long-lived branches, policy profiles, and GitHub
Environments with the same names. There is no translation layer:

| Branch | Policy profile | GitHub Environment | Purpose |
|---|---|---|---|
| `dev` | `config/environments/dev.yaml` | `dev` | Integration |
| `staging` | `config/environments/staging.yaml` | `staging` | Pre-production rehearsal |
| `prod` | `config/environments/prod.yaml` | `prod` | Production and default branch |

Approval counts do not live in YAML. Required reviewers, wait timers, branch
restrictions, environment variables, and environment secrets are configured in
GitHub Settings for each Environment.

## Promotion flow

```text
dev --source/test/security gates--> staging live gate --ff--> staging
    --production live gate-------------------------------------> prod
```

- Day-to-day changes land on `dev`.
- Pull requests run deterministic source, profile, test, documentation, and
  security gates. They never contact staging or production services.
- A push to `dev` pins one commit, validates branch lineage, and enters the
  protected `staging` GitHub Environment. Its live endpoints must pass before
  the workflow fast-forwards `staging`.
- The same tested commit then enters the protected `prod` GitHub Environment.
  Its live endpoints must pass before `prod` is fast-forwarded.
- Promotion never uses `--force`. Divergence fails with an actionable lineage
  error instead of overwriting environment history.

The workflow proves validation, protection, and branch promotion. It does not
claim an application deployment that is not defined in this checkout.

## Policy profiles

`config/environments/<env>.yaml` contains policy only:

- schema/name/description;
- runtime log level, debug, and reload policy;
- ATP strictness and default trust level; and
- branch/GitHub Environment identity.

It must not contain URLs, ports, database paths, credentials, or approval
counts. `src/utils/environments.py` validates exact fields and rejects unknown
environment names before constructing a path.

The older `.github/environments/*.yaml` files are frozen historical artifacts
covered by the active reverse-sync hold. Runtime code, hooks, and workflows do
not read them; changing or deleting them requires that hold's release process.

Select a profile with `ARTEMIS_ENV=dev|staging|prod`:

```python
from src.utils.environments import load_environment

cfg = load_environment()  # respects ARTEMIS_ENV; defaults to dev
```

## Runtime values and generated views

`config/environment-contract.yaml` owns the complete target list, generated
secret ownership, derived mappings, source discovery, and live checks.

Root `.env` is the local operator source. `./setup_secrets.sh` reconciles it
against `.env.example` and generates consumer-specific views for Express,
Vite, the Python core, the Obsidian REST shell, the Memory MCP server, and the
provenance mesh. Never edit a service view to create an independent value.

```bash
make env-check                 # tracked source/profile/template contract
make env-fix                   # deterministic policy repair only
./setup_secrets.sh             # root plus generated local views
./setup_secrets.sh --check     # local view drift, read-only
make env-live-check            # manifest-declared endpoint health
```

The pre-commit hook runs `env-fix` and never reads or writes `.env`. The
pre-push hook runs the read-only live check. Install pre-commit, pre-push, and
commit-message hooks with `make setup-hooks`.

## GitHub Environment setup

Create `dev`, `staging`, and `prod` under Settings -> Environments. Configure
reviewers and wait rules there. For protected live jobs, define:

- `PROVENANCE_SERVICE_URL` (required) as an Environment variable; and
- `ARTEMIS_PROMETHEUS_URL` (optional) when that environment exposes Prometheus.

Keep credentials in Environment secrets, not variables. Production credentials
remain inaccessible to jobs that have not entered the `prod` Environment.

Create branch/ruleset protection for `dev`, `staging`, and `prod` that matches
the direct fast-forward cascade. A rule that requires a pull request for
`staging` or `prod` will reject the workflow's intentional direct push.

## Active CI

`.github/workflows/promote.yml` is the active in-repository pipeline. This
checkout has no `.circleci/config.yml`; historical CircleCI descriptions are
not executable evidence.
