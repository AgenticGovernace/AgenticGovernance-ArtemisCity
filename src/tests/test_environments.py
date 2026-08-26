"""Behavioral tests for environment policy loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.utils import environments

VALID_PROFILE = {
    "schema_version": 1,
    "name": "staging",
    "description": "Pre-production environment.",
    "runtime": {"log_level": "INFO", "debug": False, "reload": False},
    "governance": {"strict_atp": True, "trust_default_level": 1},
    "deploy": {"branch": "staging", "github_environment": "staging"},
}


def test_environment_name_is_normalized_before_path_resolution() -> None:
    """Catch explicit names bypassing the same validation as ARTEMIS_ENV."""
    assert environments.normalize_environment_name("  STAGING  ") == "staging"

    for unsafe in ("production", "../prod", "dev.yaml", "", "staging/prod"):
        with pytest.raises(ValueError, match="dev.*staging.*prod"):
            environments.normalize_environment_name(unsafe)


def test_load_environment_rejects_filename_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catch a copied dev profile silently loading as staging or prod."""
    config_dir = tmp_path / "config" / "environments"
    config_dir.mkdir(parents=True)
    (config_dir / "staging.yaml").write_text(
        """\
schema_version: 1
name: dev
description: Wrong copied identity.
runtime:
  log_level: INFO
  debug: false
  reload: false
governance:
  strict_atp: true
  trust_default_level: 1
deploy:
  branch: staging
  github_environment: staging
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(environments, "_repo_root", lambda: tmp_path)

    with pytest.raises(ValueError, match="staging.*name"):
        environments.load_environment("staging")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            {"runtime": {"log_level": "LOUD", "debug": False, "reload": False}},
            "log_level",
        ),
        ({"deploy": {"branch": "dev", "github_environment": "staging"}}, "branch"),
        ({"approvals_required": 2}, "unknown"),
    ],
)
def test_profile_schema_rejects_malformed_or_legacy_policy(
    mutation: dict[str, object], message: str
) -> None:
    """Catch invalid types, cross-environment identity, and legacy fields."""
    profile = {
        key: (value.copy() if isinstance(value, dict) else value)
        for key, value in VALID_PROFILE.items()
    }
    if "approvals_required" in mutation:
        profile["deploy"]["approvals_required"] = mutation["approvals_required"]
    else:
        profile.update(mutation)

    with pytest.raises(ValueError, match=message):
        environments.validate_environment_profile(profile, "staging")


def test_real_profiles_are_policy_only_and_self_identifying() -> None:
    """Catch endpoint, credential, model, or machine-path values returning to YAML."""
    expected_keys = {
        "schema_version",
        "name",
        "description",
        "runtime",
        "governance",
        "deploy",
    }
    expected_runtime = {
        "dev": {"log_level": "TRACE", "debug": True, "reload": True},
        "staging": {"log_level": "INFO", "debug": False, "reload": False},
        "prod": {"log_level": "WARN", "debug": False, "reload": False},
    }

    for name in environments.VALID_ENVIRONMENTS:
        profile = environments.load_environment(name)
        assert set(profile) == expected_keys
        assert profile["name"] == name
        assert profile["deploy"] == {
            "branch": name,
            "github_environment": name,
        }
        assert profile["runtime"] == expected_runtime[name]
