# Environment branching

Artemis City uses three long-lived environment branches that map 1:1 to
GitHub Environments and deploy targets.

| Branch    | GitHub Environment | Purpose                                       | Approvals |
|-----------|--------------------|-----------------------------------------------|-----------|
| `dev`     | `dev`              | Integration of feature work                   | 0         |
| `staging` | `staging`          | Pre-production rehearsal, synthetic data      | 1         |
| `prod`    | `prod`             | Production. Default branch.                   | 2         |

## Flow

```
feature/* --PR--> dev --PR--> staging --PR--> prod
```

- Feature branches always target `dev`.
- Promote `dev -> staging` and `staging -> prod` either by opening a PR
  manually or by running the `Promote` workflow from the Actions tab.
- `prod` is protected; only promotion PRs merged from `staging` may land
  there.

## Config

Each environment has a YAML file in `config/environments/<env>.yaml`.
Pick the active environment with the `ARTEMIS_ENV` variable; loading is
handled by `src/utils/environments.py`:

```python
from src.utils.environments import load_environment
cfg = load_environment()  # respects ARTEMIS_ENV, defaults to dev
```

## Secrets

Secrets are scoped per GitHub Environment, not per repo, so production
credentials are unreachable from `dev` or `staging` deploys. Required
approvals are configured on the Environment itself in repo Settings.

## Workflows

- `ci.yml` runs on every push and PR to `dev`, `staging`, `prod`.
- `deploy.yml` runs on push to an env branch and deploys to the matching
  GitHub Environment. The deploy step is a provider-agnostic placeholder;
  wire your container build or `aws`/`az`/`gcloud` deploy action there.
- `promote.yml` opens a draft promotion PR (`dev -> staging` or
  `staging -> prod`) on demand.

## One-time setup (after merge)

1. Rename `main` -> `prod` in repo Settings -> Branches and set `prod` as
   the default branch.
2. Create the `dev` and `staging` branches from `prod` if they do not yet
   exist.
3. Under Settings -> Environments, create `dev`, `staging`, `prod` and
   attach any required reviewers / wait timers and per-env secrets.
4. Add branch protection rules requiring CI green and the configured
   number of approvals before merging into each env branch. These live
   under Settings -> Rules -> Rulesets as `Protect dev`, `Protect
   staging`, and `Protect prod`.
