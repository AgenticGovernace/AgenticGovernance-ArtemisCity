"""Behavioral tests for source, template, fix, setup, and live env contracts."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts import environment_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def _profile(name: str) -> str:
    log_level, debug, reload, trust = {
        "dev": ("TRACE", "true", "true", 2),
        "staging": ("INFO", "false", "false", 1),
        "prod": ("WARN", "false", "false", 1),
    }[name]
    description = {
        "dev": "Local and shared developer integration environment.",
        "staging": (
            "Pre-production environment mirroring production policy with synthetic data."
        ),
        "prod": (
            "Production environment reached only through the reviewed promotion cascade."
        ),
    }[name]
    return f"""\
schema_version: 1
name: {name}
description: {description}
runtime:
  log_level: {log_level}
  debug: {debug}
  reload: {reload}
governance:
  strict_atp: true
  trust_default_level: {trust}
deploy:
  branch: {name}
  github_environment: {name}
"""


def _contract_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config/environments").mkdir(parents=True)
    (root / "src").mkdir()
    for name in ("dev", "staging", "prod"):
        (root / f"config/environments/{name}.yaml").write_text(
            _profile(name), encoding="utf-8"
        )
    (root / ".env.example").write_text(
        "ARTEMIS_ENV=dev\nKNOWN_VALUE=1\n", encoding="utf-8"
    )
    (root / "src/.env.example").write_text(
        "ARTEMIS_ENV=dev\nKNOWN_VALUE=1\n", encoding="utf-8"
    )
    (root / "config/environment-contract.yaml").write_text(
        """\
schema_version: 1
targets:
  - name: root
    template: .env.example
    output: .env
  - name: core
    template: src/.env.example
    output: src/.env
generated_secrets: []
derived_values: {}
ignored_source_variables: []
source_globs:
  - src/**/*.py
live_checks: []
""",
        encoding="utf-8",
    )
    return root


def test_check_reports_code_variable_missing_from_root_inventory(
    tmp_path: Path,
) -> None:
    """Catch a new runtime getenv call that no template or setup flow covers."""
    root = _contract_fixture(tmp_path)
    (root / "src/app.py").write_text(
        'import os\nVALUE = os.getenv("MISSING_ENDPOINT")\n', encoding="utf-8"
    )

    errors = environment_config.check_repository(root)

    assert errors == [
        "code-discovered variable MISSING_ENDPOINT is missing from .env.example"
    ]


def test_check_reports_shell_default_missing_from_root_inventory(
    tmp_path: Path,
) -> None:
    """Catch a launch-script environment override omitted from provisioning."""
    root = _contract_fixture(tmp_path)
    contract_path = root / "config/environment-contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["source_globs"] = ["src/**/*.sh"]
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )
    (root / "src/launch.sh").write_text(
        'PORT="${MISSING_SERVICE_PORT:-8787}"\n', encoding="utf-8"
    )

    errors = environment_config.check_repository(root)

    assert errors == [
        "code-discovered variable MISSING_SERVICE_PORT is missing from .env.example"
    ]


def test_check_rejects_duplicate_template_declarations(tmp_path: Path) -> None:
    """Catch ambiguous env files where later declarations silently win."""
    root = _contract_fixture(tmp_path)
    (root / ".env.example").write_text(
        "ARTEMIS_ENV=dev\nKNOWN_VALUE=1\nKNOWN_VALUE=2\n", encoding="utf-8"
    )

    errors = environment_config.check_repository(root)

    assert errors == [".env.example declares KNOWN_VALUE more than once"]


def test_check_rejects_runtime_template_missing_from_manifest(tmp_path: Path) -> None:
    """A newly added service template cannot bypass root provisioning."""
    root = _contract_fixture(tmp_path)
    undeclared = root / "src/new-service/.env.example"
    undeclared.parent.mkdir(parents=True)
    undeclared.write_text("KNOWN_VALUE=1\n", encoding="utf-8")

    errors = environment_config.check_repository(root)

    assert errors == [
        (
            "runtime template src/new-service/.env.example is not declared in "
            "config/environment-contract.yaml"
        )
    ]


def test_fix_profiles_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    """Catch hooks repeatedly rewriting policy or leaving copied dev identity."""
    root = _contract_fixture(tmp_path)
    staging = root / "config/environments/staging.yaml"
    staging.write_text(
        """\
name: dev
description: Copied development values.
mcp:
  base_url: http://localhost:3000
governance:
  strict_atp: true
  trust_default_level: 2
deploy:
  branch: dev
  github_environment: dev
  approvals_required: 0
""",
        encoding="utf-8",
    )

    first = environment_config.fix_profiles(root)
    second = environment_config.fix_profiles(root)

    assert first == [staging]
    assert second == []
    repaired = yaml.safe_load(staging.read_text(encoding="utf-8"))
    assert repaired["name"] == "staging"
    assert repaired["runtime"] == {
        "log_level": "INFO",
        "debug": False,
        "reload": False,
    }
    assert repaired["deploy"] == {
        "branch": "staging",
        "github_environment": "staging",
    }
    assert "mcp" not in repaired


def test_repository_canonical_environment_policy_has_no_contract_drift() -> None:
    """Catch canonical policy, source-inventory, or template drift."""
    assert environment_config.check_repository(REPO_ROOT) == []


def test_live_check_uses_declared_endpoint_and_skips_unconfigured_optional(
    tmp_path: Path,
) -> None:
    """Live gates use the manifest and do not invent optional service URLs."""
    root = _contract_fixture(tmp_path)
    contract_path = root / "config/environment-contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["live_checks"] = [
        {
            "name": "required",
            "url_variable": "REQUIRED_URL",
            "path": "/health",
            "required": True,
        },
        {
            "name": "optional",
            "url_variable": "OPTIONAL_URL",
            "path": "/ready",
            "required": False,
        },
    ]
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )
    calls: list[tuple[str, float]] = []

    def fetch_status(url: str, timeout: float) -> int:
        calls.append((url, timeout))
        return 204

    errors = environment_config.live_check_environment(
        root,
        {"REQUIRED_URL": "https://required.example.test/base"},
        fetch_status=fetch_status,
    )

    assert errors == []
    assert calls == [("https://required.example.test/base/health", 5.0)]


def test_live_check_reports_missing_required_url_without_exposing_values(
    tmp_path: Path,
) -> None:
    """A protected live gate fails closed when its required URL is absent."""
    root = _contract_fixture(tmp_path)
    contract_path = root / "config/environment-contract.yaml"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    contract["live_checks"] = [
        {
            "name": "required",
            "url_variable": "REQUIRED_URL",
            "path": "/health",
            "required": True,
        }
    ]
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )

    errors = environment_config.live_check_environment(root, {})

    assert errors == ["required live check requires REQUIRED_URL"]
