# Environment branching

Artemis City uses three long-lived environment branches that map 1:1 to
GitHub Environments and deploy targets. The names `dev`, `staging`, and
`prod` are kept identical across the branch, the GitHub Environment, and
the file under `config/environments/` so there is no mapping layer to
forget.

| Branch    | GitHub Environment | Purpose                                       | Approvals |
|-----------|--------------------|-----------------------------------------------|-----------|
| `dev`     | `dev`              | Integration of feature work                   | 0         |
| `staging` | `staging`          | Pre-production rehearsal, synthetic data      | 1         |
| `prod`    | `prod`             | Production. Default branch.                   | 2         |

## Flow

```
feature/* --PR--> dev --push--> [Promote cascade] --ff--> staging --ff--> prod
```

- Feature branches always target `dev`. Day to day you only touch `dev`.
- A **push to `dev`** triggers the `Promote` cascade (`promote.yml`): it
  runs the test gate, then fast-forwards `staging` to the tested commit,
  deploys `staging`, fast-forwards `prod`, and deploys `prod` — all in one
  run, with no manual branch surgery.
- Promotion advances the env branches with a plain `git push` of the tested
  commit, **not** a promotion pull request. Because `dev` is never used as a
  PR head branch, it is never auto-deleted — you no longer have to recreate
  `dev` after every promotion.
- Approval gates live on the GitHub **Environments**, not on branch PRs: if
  the `staging` / `prod` Environments have required reviewers, the matching
  deploy job pauses for approval before it runs. The cascade still flows
  hands-off through any environment that has zero required reviewers.
- The cascade is fast-forward only (no `--force`). If `staging` or `prod`
  was diverged outside the cascade, the push fails loudly instead of
  clobbering history.

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

CircleCI (`.circleci/config.yml`) is the primary CI/CD system: it runs the
test matrix, docs-mirror and secrets checks on every push, and owns the
per-environment deploy workflows with their approval gates.

GitHub Actions retains only the promotion cascade:

- `promote.yml` is the promotion cascade. On a push to `dev` (or manual
  dispatch) it runs the test gate and then advances `staging` and `prod`
  by fast-forward. It needs `contents: write` to move the branch
  pointers. Advancing an environment branch is what triggers the
  corresponding CircleCI deploy workflow.

> **Note on `GITHUB_TOKEN` and branch protection.** If you protect
> `staging` / `prod` with rules that *require a pull request*, the
> cascade's direct push will be rejected — gate those environments with
> **required reviewers / approvals in CircleCI** instead, and keep
> "Automatically delete head branches" off so manual PRs never eat `dev`.

## One-time setup (after merge)

1. Rename `main` -> `prod` in repo Settings -> Branches and set `prod` as
   the default branch.
2. Create the `dev` and `staging` branches from `prod` if they do not yet
   exist.
3. Under Settings -> Environments, create `dev`, `staging`, `prod` and
   attach any required reviewers / wait timers and per-env secrets.
4. Add branch protection rules requiring CI green and the configured
   number of approvals before merging into each env branch. These rules
   live under Settings -> Rules -> Rulesets as `Protect dev`,
   `Protect staging`, and `Protect prod`.
