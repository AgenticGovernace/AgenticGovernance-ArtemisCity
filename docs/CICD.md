# CI/CD Pipeline Documentation

This document describes the Continuous Integration and Continuous Deployment (CI/CD) pipeline for Artemis City.

## Table of Contents

1. [Overview](#overview)
2. [Workflows](#workflows)
3. [Pipeline Stages](#pipeline-stages)
4. [Configuration](#configuration)
5. [Secrets Management](#secrets-management)
6. [Release Process](#release-process)
7. [Troubleshooting](#troubleshooting)

## Overview

Artemis City deploys across three long-lived environment branches —
`dev`, `staging`, `prod` — that map 1:1 to GitHub Environments. See
`docs/ENVIRONMENTS.md` for the branch model; this document covers the
pipeline that drives it.

GitHub Actions provides four workflows:

- **CI** (`ci.yml`): tests + config validation on every push/PR to the
  env branches.
- **Promote** (`promote.yml`): the promotion cascade. A push to `dev`
  flows automatically to `staging` and then `prod`.
- **Deploy** (`deploy.yml`): deploys a commit to its matching GitHub
  Environment. Runs on direct push, manual dispatch, or as the reusable
  workflow the cascade calls.
- **Dependency Submission** (`dependency-submission.yml`): best-effort
  dependency-graph snapshot (non-blocking).

CircleCI (`.circleci/config.yml`) runs an equivalent build-and-test job
as a second, provider-independent signal.

### Technology Stack

- **CI Platform**: GitHub Actions (plus CircleCI mirror)
- **Python Testing**: pytest (`src/tests`)
- **Supported Python**: 3.11, 3.12, 3.13 (`requires-python = ">=3.11,<3.15"`)
- **Environment model**: `dev -> staging -> prod` (see `docs/ENVIRONMENTS.md`)

## Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

**Triggers:**

- Push to `dev`, `staging`, or `prod`
- Pull requests targeting `dev`, `staging`, or `prod`
- Manual dispatch

**Jobs:**

- **docs-mirror**: fails if `CLAUDE.md` and `AGENTS.md` are not
  byte-for-byte identical.
- **python**: matrix over Python 3.11 / 3.12 / 3.13 —
    - installs `requirements.txt` + `requirements-dev.txt`,
    - validates every `config/environments/*.yaml` via
      `src.utils.environments.load_environment`,
    - runs `python -m pytest src/tests`.

### 2. Promote Workflow (`.github/workflows/promote.yml`)

The promotion cascade. See `docs/ENVIRONMENTS.md` for the full branch
model.

**Triggers:**

- Push to `dev`
- Manual dispatch (promotes the current `dev` tip)

**Jobs (sequential):**

1. **test** — test gate (same checks as CI). Nothing promotes unless this
   is green.
2. **promote-staging** — fast-forwards `staging` to the tested commit with
   `git push` (no PR, no branch deletion).
3. **deploy-staging** — calls `deploy.yml` (reusable) for the `staging`
   Environment.
4. **promote-prod** — fast-forwards `prod` to the same commit.
5. **deploy-prod** — calls `deploy.yml` for the `prod` Environment.

Approvals are enforced by required reviewers on the `staging` / `prod`
GitHub Environments, so the cascade pauses for sign-off where configured
and flows straight through where not.

### 3. Deploy Workflow (`.github/workflows/deploy.yml`)

**Triggers:**

- Push to `dev`, `staging`, or `prod`
- Manual dispatch (pick the environment)
- `workflow_call` — reusable entry point used by the Promote cascade

**Jobs:**

- **resolve**: picks the target environment from the `environment` input
  (dispatch/call) or the branch name (push).
- **deploy**: binds to the matching GitHub Environment, loads its
  `config/environments/<env>.yaml`, then runs the provider-agnostic
  build + deploy placeholder steps.

### 4. Dependency Submission (`.github/workflows/dependency-submission.yml`)

**Triggers:**

- Push / PR to `dev`, `staging`, `prod`
- Manual dispatch

Submits a best-effort dependency-graph snapshot for `../src/pyproject.toml`. The
job is `continue-on-error`, so it never blocks the pipeline.

### CircleCI mirror (`.circleci/config.yml`)

A single `build-and-test` job on `cimg/python:3.12` that installs the
requirements, validates the environment configs, and runs
`pytest src/tests` — a provider-independent copy of the GitHub CI signal.

## Pipeline Stages

### Stage 1: Code Quality (Fast Feedback)

**Duration**: ~2-3 minutes

- Formatting checks
- Linting
- Import sorting

**Gates**: Must pass for PR merge

### Stage 2: Security Scanning

**Duration**: ~3-5 minutes

- Secret detection
- Vulnerability scanning
- Security linting

**Gates**: Blocking for critical vulnerabilities

### Stage 3: Testing

**Duration**: ~5-10 minutes

- Unit tests (multi-version)
- Integration tests
- Coverage reporting

**Gates**: Must pass, coverage threshold recommended

### Stage 4: Build & Package

**Duration**: ~2-4 minutes

- Python package build
- TypeScript compilation
- Artifact creation

**Gates**: Must build successfully

### Stage 5: Deployment (Release only)

**Duration**: ~5-10 minutes

- GitHub release creation
- PyPI publication
- Docker image build

**Gates**: Release gates configured in GitHub

## Configuration

### Environment Variables

Set in workflow files:

```yaml
env:
  PYTHON_VERSION: '3.13'
  NODE_VERSION: '18'
```

### Matrix Testing

Python version matrix:

```yaml
strategy:
  matrix:
    python-version: ['3.11', '3.12', '3.13']
```

### Caching

Dependency caching enabled:

```yaml
- uses: actions/setup-python@v5
  with:
    cache: 'pip'

- uses: actions/setup-node@v4
  with:
    cache: 'npm'
```

## Secrets Management

### Required Secrets

**For PyPI Publication:**

- No secrets needed (uses trusted publisher)

**For Docker (Optional):**

- `DOCKER_USERNAME`: Docker Hub username
- `DOCKER_PASSWORD`: Docker Hub token

**Automatic:**

- `GITHUB_TOKEN`: Automatically provided

### Setting Secrets

```bash
# Via GitHub CLI
gh secret set DOCKER_USERNAME --body "your-username"
gh secret set DOCKER_PASSWORD --body "your-token"

# Via GitHub UI
# Settings → Secrets and variables → Actions → New repository secret
```

### Security Best Practices

1. Never commit secrets to repository
2. Use GitHub encrypted secrets
3. Rotate secrets regularly
4. Use least-privilege access
5. Enable secret scanning in repository

## Release Process

### Creating a Release

**1. Update version in `../src/pyproject.toml`:**

```toml
[project]
version = "1.0.0"
```

**2. Update CHANGELOG.md:**

```markdown
## [1.0.0] - 2025-11-23
### Added
- New feature X
### Fixed
- Bug Y
```

**3. Commit changes:**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "Release v1.0.0"
git push origin prod
```

**4. Create and push tag:**

```bash
git tag v1.0.0
git push origin v1.0.0
```

**5. Workflow automatically:**

- Builds package
- Creates GitHub release
- Publishes to PyPI
- Builds Docker image (if enabled)

### Version Numbering

Follow Semantic Versioning (SemVer):

- **Major** (1.0.0): Breaking changes
- **Minor** (0.1.0): New features, backward compatible
- **Patch** (0.0.1): Bug fixes

Pre-release versions:

- `v1.0.0-alpha.1`: Alpha release
- `v1.0.0-beta.1`: Beta release
- `v1.0.0-rc.1`: Release candidate

### Rollback Procedure

**If release fails:**

1. Delete the tag:
   ```bash
   git tag -d v1.0.0
   git push origin :refs/tags/v1.0.0
   ```

2. Fix issues locally

3. Re-create tag:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

**If package is published:**

- Cannot delete from PyPI
- Publish a new patch version
- Mark previous version as yanked

## Troubleshooting

### Common Issues

#### 1. Linting Failures

**Problem**: Black or Flake8 fails

**Solution**:

```bash
# Format locally
make format

# Check before commit
make check
```

#### 2. Test Failures

**Problem**: Tests pass locally but fail in CI

**Check**:

- Python version differences
- Environment variables
- File paths (use absolute or relative consistently)
- Time-dependent tests

**Solution**:

```bash
# Test with specific Python version
python3.8 -m pytest

# Run in clean environment
python -m venv clean_env
source clean_env/bin/activate
pip install -r requirements.txt
pytest
```

#### 3. Build Failures

**Problem**: Package build fails

**Check**:

- `../src/pyproject.toml` syntax
- Missing files in MANIFEST.in
- Build dependencies

**Solution**:

```bash
# Test build locally
python -m build
twine check dist/*
```

#### 4. Secret Scanning False Positives

**Problem**: Gitleaks detects false positives

**Solution**:

Create `.gitleaks.toml`:

```toml
[allowlist]
paths = [
    ".env.example",
    ".env.template"
]
```

#### 5. Dependency Conflicts

**Problem**: pip install fails in CI

**Solution**:

```bash
# Update dependencies
pip install --upgrade -r requirements.txt

# Create fresh requirements
pip freeze > requirements.txt

# Use pip-tools for better management
pip install pip-tools
pip-compile requirements.in
```

### Workflow Debugging

**View logs:**

```bash
# Via GitHub CLI
gh run list
gh run view <run-id>
gh run view <run-id> --log
```

**Re-run failed jobs:**

```bash
gh run rerun <run-id>
gh run rerun <run-id> --failed
```

**Download artifacts:**

```bash
gh run download <run-id>
```

## Best Practices

### For Developers

1. **Run checks locally before pushing:**
   ```bash
   make check
   make test
   make security
   ```

2. **Keep CI fast:**
    - Use caching
    - Parallelize jobs
    - Fail fast on critical errors

3. **Write deterministic tests:**
    - No time-dependent behavior
    - No network dependencies (use mocks)
    - No file system dependencies

4. **Update workflows regularly:**
    - Keep actions up to date
    - Review security advisories
    - Test new Python/Node versions

### For Maintainers

1. **Monitor workflow runs:**
    - Set up notifications
    - Review failed runs promptly
    - Update on breaking changes

2. **Manage secrets securely:**
    - Rotate regularly
    - Use least privilege
    - Document usage

3. **Review dependency updates:**
    - Check weekly reports
    - Test updates locally
    - Update gradually

4. **Maintain documentation:**
    - Update on workflow changes
    - Document new secrets
    - Keep examples current

## Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Python Packaging Guide](https://packaging.python.org/)
- [Semantic Versioning](https://semver.org/)
- [Codecov Documentation](https://docs.codecov.io/)
- [Docker Hub Documentation](https://docs.docker.com/docker-hub/)

## Support

For CI/CD issues:

1. Check workflow logs
2. Review this documentation
3. Search existing issues
4. Open new issue with:
    - Workflow run URL
    - Error messages
    - Steps to reproduce
    - Local environment details

---

**Workflow Status Badges:**

Add to README.md:

```markdown
![CI](https://github.com/yourusername/artemis-city/workflows/CI/badge.svg)
![Release](https://github.com/yourusername/artemis-city/workflows/Release/badge.svg)
[![codecov](https://codecov.io/gh/yourusername/artemis-city/branch/prod/graph/badge.svg)](https://codecov.io/gh/yourusername/artemis-city)
```
