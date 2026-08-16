"""Regression tests for the repository's Make and dependency ownership contract."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import yaml
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
ROOT_MAKEFILE = ROOT / "Makefile"
LAUNCH_DIR = ROOT / "src" / "launch"
LAUNCH_MAKEFILE = LAUNCH_DIR / "Makefile"
RELEASE_HOLD_MESSAGE = "RELEASE_HOLD_ACTIVE: Python package release is blocked."


def _make_dry_run(directory: Path, target: str) -> str:
    """Return the commands Make would run without executing normal recipes."""

    result = subprocess.run(
        ["make", "--no-print-directory", "--warn-undefined-variables", "-n", target],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "warning: undefined variable" not in result.stderr.lower(), result.stderr
    return result.stdout


def _run_make(directory: Path, target: str) -> subprocess.CompletedProcess[str]:
    """Run one Make target and return its captured result."""

    return subprocess.run(
        ["make", "--no-print-directory", "--warn-undefined-variables", target],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )


def _target_names(makefile: Path) -> set[str]:
    """Extract concrete target names from a Makefile."""

    return {
        match.group(1)
        for line in makefile.read_text(encoding="utf-8").splitlines()
        if (match := re.match(r"^([A-Za-z][A-Za-z0-9_-]*):", line))
    }


def _requirements(path: Path) -> list[Requirement]:
    """Parse direct requirement declarations, ignoring comments and includes."""

    requirements: list[Requirement] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            requirements.append(Requirement(line))
    return requirements


def test_root_install_dev_is_one_locked_uv_transaction() -> None:
    output = _make_dry_run(ROOT, "install-dev")

    assert "pipenv" not in output.lower()
    assert output.count("uv sync") == 1
    assert "--locked" in output
    assert "--all-extras" in output
    assert f'VIRTUAL_ENV="{ROOT / ".venv"}"' in output
    assert f"--python {ROOT / '.venv/bin/python'}" in output


def test_root_python_targets_use_the_canonical_environment() -> None:
    expected_modules = {
        "test": "pytest",
        "api": "uvicorn",
        "build": "build",
        "docs": "mkdocs",
    }

    for target, module in expected_modules.items():
        output = _make_dry_run(ROOT, target)
        assert f"{ROOT / '.venv/bin/python'} -m {module}" in output


def test_root_owns_installation_services_and_documentation() -> None:
    targets = _target_names(ROOT_MAKEFILE)

    assert {
        "venv",
        "install",
        "install-dev",
        "install-web",
        "install-all",
        "frontend",
        "api",
        "express-api",
        "docs",
        "docs-serve",
    } <= targets


def test_release_hold_targets_are_root_owned_and_phony() -> None:
    targets = _target_names(ROOT_MAKEFILE)
    makefile_text = ROOT_MAKEFILE.read_text(encoding="utf-8")
    phony_block = makefile_text.split(".DEFAULT_GOAL", maxsplit=1)[0]

    assert {"package-audit", "package-check"} <= targets
    assert "package-audit" in phony_block
    assert "package-check" in phony_block


def test_package_audit_selects_only_release_hold_contract_tests() -> None:
    output = _make_dry_run(ROOT, "package-audit")

    assert "src/tests/test_release_artifacts.py" in output
    assert "-k release_hold_contract" in output
    assert "src/tests/test_repository_boundaries.py" not in output
    assert "python -m build" not in output


def test_package_check_exits_two_with_the_stable_hold_message() -> None:
    result = _run_make(ROOT, "package-check")
    output = result.stdout + result.stderr

    assert result.returncode == 2
    assert RELEASE_HOLD_MESSAGE in output
    assert "python -m build" not in output


def test_build_keeps_its_recipe_dormant_behind_the_release_hold() -> None:
    output = _make_dry_run(ROOT, "build")
    makefile_text = ROOT_MAKEFILE.read_text(encoding="utf-8")

    audit_index = output.index("src/tests/test_release_artifacts.py")
    hold_index = output.index(RELEASE_HOLD_MESSAGE)
    build_index = output.index("python -m build")
    assert audit_index < hold_index < build_index
    assert re.search(r"^package-check: package-audit", makefile_text, re.MULTILINE)
    assert re.search(r"^build: package-check", makefile_text, re.MULTILINE)
    assert makefile_text.count("$(PYTHON) -m build") == 1


def test_launch_makefile_contains_only_application_feature_targets() -> None:
    targets = _target_names(LAUNCH_MAKEFILE)
    required = {
        "help",
        "run",
        "cli",
        "atp",
        "orchestrator",
        "kernel",
        "demo",
        "demo-artemis",
        "demo-memory",
        "demo-postal",
        "hebbian",
        "agent-stats",
    }
    infrastructure = {
        "venv",
        "install",
        "install-dev",
        "install-web",
        "install-all",
        "setup-hooks",
        "lint",
        "lint-fix",
        "format",
        "check",
        "security",
        "secrets",
        "test",
        "test-cov",
        "pre-commit",
        "pre-commit-update",
        "clean",
        "clean-env",
        "server",
        "frontend",
        "api",
        "dashboard-api",
        "express-api",
        "build",
        "web-build",
        "docs",
        "docs-serve",
        "all",
        "ci",
    }

    assert required <= targets
    assert not targets & infrastructure

    launch_text = LAUNCH_MAKEFILE.read_text(encoding="utf-8").lower()
    for forbidden_install in (
        "uv sync",
        "uv pip",
        "pip install",
        "pipenv install",
        "poetry install",
        "npm install",
        "npm ci",
        "pnpm install",
        "yarn install",
    ):
        assert forbidden_install not in launch_text


def test_launch_features_use_the_root_virtual_environment() -> None:
    for target in ("cli", "orchestrator", "kernel", "demo-artemis"):
        output = _make_dry_run(LAUNCH_DIR, target)
        assert str(ROOT / ".venv/bin/python") in output


def test_python_dependency_groups_are_real_extras_without_runtime_pytest() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    extras = project["optional-dependencies"]

    assert {"dev", "docs", "lint", "test", "build"} <= extras.keys()
    assert any(
        requirement.startswith("mkdocs-mermaid2-plugin")
        for requirement in extras["docs"]
    )
    assert any("pytest>=9.0.3,<9.1" == requirement for requirement in extras["test"])
    assert all(
        not requirement.lower().startswith("pytest")
        for requirement in project["dependencies"]
    )


def test_pyproject_will_only_collect_src_tests_after_task_5() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = pyproject["tool"]["pytest"]["ini_options"]

    assert pytest_options["testpaths"] == ["src/tests"], (
        "TASK_5_TEST_COLLECTION_ROOT: pyproject.toml must declare only "
        "['src/tests'] once the legacy root tests tree is retired."
    )


def test_requirement_files_have_one_owner_per_normalized_name() -> None:
    runtime = _requirements(ROOT / "requirements.txt")
    development = _requirements(ROOT / "requirements-dev.txt")
    docker = _requirements(ROOT / "requirements-docker.txt")

    for requirements in (runtime, development, docker):
        names = [
            requirement.name.lower().replace("_", "-") for requirement in requirements
        ]
        assert len(names) == len(set(names))

    runtime_names = {requirement.name.lower() for requirement in runtime}
    development_names = {requirement.name.lower() for requirement in development}
    assert runtime_names.isdisjoint(development_names)

    assert all(requirement.name.lower() != "pytest" for requirement in runtime)
    pytest_requirements = [
        requirement
        for requirement in development
        if requirement.name.lower() == "pytest"
    ]
    assert len(pytest_requirements) == 1
    assert str(pytest_requirements[0].specifier) == "<9.1,>=9.0.3"


def test_runtime_container_does_not_install_node_vite_from_pypi() -> None:
    runtime = _requirements(ROOT / "requirements-runtime.txt")

    assert all(requirement.name.lower() != "vite" for requirement in runtime)


def test_setup_entrypoint_delegates_installation_to_root_make() -> None:
    setup_script = (ROOT / "src/Experiments/legal_summarization/.SETUP.py").read_text(
        encoding="utf-8"
    )

    assert '["make", "install-all"]' in setup_script
    assert '"uv", "sync"' not in setup_script
    assert "npm install" not in setup_script


def test_root_owns_workspace_script_policy() -> None:
    root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    frontend_package = json.loads(
        (ROOT / "app/web/frontend/package.json").read_text(encoding="utf-8")
    )

    assert root_package["workspaces"] == ["app/api", "app/web/frontend"]
    assert "allowScripts" in root_package
    assert "allowScripts" not in frontend_package
    assert "overrides" not in frontend_package


def test_legacy_launch_package_delegates_feature_commands_only() -> None:
    launch_package = json.loads(
        (ROOT / "src/launch/package.json").read_text(encoding="utf-8")
    )
    scripts = launch_package["scripts"]

    assert set(scripts) == {
        "start",
        "cli",
        "atp",
        "orchestrator",
        "kernel",
        "demo",
        "demo:artemis",
        "demo:memory",
        "demo:postal",
    }
    assert all("make --no-print-directory" in command for command in scripts.values())
    assert all("python" not in command for command in scripts.values())
    assert all("install" not in command for command in scripts.values())


def test_clean_env_validates_a_real_non_symlink_virtual_environment() -> None:
    output = _make_dry_run(ROOT, "clean-env")

    assert "pyvenv.cfg" in output
    assert "symbolic link" in output
    assert "Refusing to remove unsafe environment path" in output


def test_hatch_configuration_remains_unchanged_while_release_hold_is_active() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["build-system"]["build-backend"] == "hatchling.build"
    targets = pyproject["tool"]["hatch"]["build"]["targets"]
    wheel_config = targets["wheel"]
    assert wheel_config["only-include"] == ["src", "app"]
    assert set(wheel_config["exclude"]) == {
        "/app/api/**",
        "/app/scripts/**",
        "/app/web/**",
    }
    assert "sdist" not in targets


def test_promote_delegates_dependency_installation_to_root_make() -> None:
    workflow = (ROOT / ".github/workflows/promote.yml").read_text(encoding="utf-8")

    assert "make install-dev" in workflow
    assert "make lint" in workflow
    assert "make test" in workflow
    assert "make docs" in workflow
    assert "uv pip install" not in workflow
    assert ".venv/bin/ruff" not in workflow
    assert ".venv/bin/python -m pytest" not in workflow


def test_root_lint_matches_the_promote_undefined_name_gate() -> None:
    output = _make_dry_run(ROOT, "lint")

    assert "ruff check src app/api/main.py" in output
    assert "--select F821" in output
    assert "--exclude '**/.virtual_documents/**'" in output


def test_mkdocs_configuration_owns_the_active_documentation_tree() -> None:
    config_path = ROOT / "mkdocs.yml"
    assert config_path.is_file()
    assert (ROOT / "docs/index.md").is_file()

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["docs_dir"] == "docs"
    assert config["site_dir"] == "dist/docs"
    assert config["theme"]["name"] == "material"
    assert "mermaid2" in config["plugins"]
    assert config["nav"][0] == {"Home": "index.md"}
