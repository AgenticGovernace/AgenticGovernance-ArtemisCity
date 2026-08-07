"""Behavioral contract for the shared QuantumHarmony ignore baseline."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROOT_GITIGNORE = ROOT / ".gitignore"


def _check_ignore(
    path: str, *, verbose: bool = True
) -> subprocess.CompletedProcess[str]:
    """Ask Git whether a hypothetical path is ignored by repository policy."""

    reporting_flag = "--verbose" if verbose else "--quiet"
    return subprocess.run(
        ["git", "check-ignore", "--no-index", reporting_flag, "--", path],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "path",
    [
        ".dbeaver/data-sources.json",
        ".project",
        ".settings/org.eclipse.core.resources.prefs",
        "services/catalog/.env.production",
        "services/catalog/private.pem",
        "services/catalog/__pycache__/models.cpython-312.pyc",
        "services/catalog/.venv/bin/python",
        "apps/dashboard/node_modules/react/index.js",
        "apps/dashboard/.next/cache/build-manifest.json",
        "apps/dashboard/dist/assets/app.js",
        "services/catalog/bin/Debug/net8.0/catalog.dll",
        "services/catalog/.pytest_cache/v/cache/nodeids",
        "services/catalog/.ruff_cache/content",
        "apps/dashboard/coverage/lcov.info",
        "apps/dashboard/playwright-report/index.html",
        "infra/.terraform/providers/registry.json",
        "infra/production.tfstate.backup",
        "services/catalog/runtime.sqlite-wal",
        "services/catalog/debug.log",
        "apps/dashboard/.DS_Store",
        "data/run_logs.db",
        "src/data/vector_store.db",
        "logs/run_20260806.md",
        ".agents/.codex/auth.json",
        "supabase/.temp/project-ref",
        "notebooks/.virtual_documents/analysis.py",
    ],
)
def test_local_generated_or_sensitive_paths_are_ignored_by_repo_policy(
    path: str,
) -> None:
    """A missing baseline rule must not let machine-local state reach staging."""

    result = _check_ignore(path)

    assert result.returncode == 0, result.stderr or f"expected {path!r} to be ignored"
    source = result.stdout.split(":", 1)[0]
    assert (ROOT / source).resolve() == ROOT_GITIGNORE.resolve(), result.stdout


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "services/catalog/.env.template",
        "services/catalog/.env.production.example",
        "services/catalog/.env.staging.template",
        ".secrets.baseline",
        "schemas/event.schema.json",
        "supabase/migrations/20260806_initial.sql",
        "tests/fixtures/request.json",
        "tests/fixtures/sample.db",
        "services/catalog/schema.sqlite",
        "database/initial.seed",
        "services/catalog/logs/schema-notes.md",
        "site/content/index.md",
        "bin/bootstrap",
        "vendor/wheels/offline-runtime.whl",
        "src/.project",
        "services/catalog/.settings/checkstyle.prefs",
        "docs/.dbeaver/example-project.json",
        "src/data/schema.json",
        "app/scripts/data/vector_store.db",
        "package-lock.json",
        "services/catalog/package-lock.json",
        "uv.lock",
        "Cargo.lock",
        "renv.lock",
        ".terraform.lock.hcl",
        ".vscode/settings.json",
        ".vscode/tasks.json",
        ".ai/AGENTS.md",
        ".github/workflows/promote.yml",
        "gradle/wrapper/gradle-wrapper.jar",
        "release/source-provenance.zip",
        "noarch/current_repodata.json",
    ],
)
def test_shared_source_and_reproducibility_assets_remain_trackable(path: str) -> None:
    """An overbroad baseline must not hide portable project resources."""

    result = _check_ignore(path, verbose=False)

    assert result.returncode == 1, result.stdout or result.stderr
