"""Environment configuration loader for Artemis City.

The active environment is selected via the ``ARTEMIS_ENV`` variable
(``dev``, ``staging``, ``prod``). Each environment maps to a YAML file in
``config/environments/`` and a same-named long-lived git branch.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

VALID_ENVIRONMENTS = ("dev", "staging", "prod")
DEFAULT_ENVIRONMENT = "dev"
PROFILE_KEYS = frozenset(
    {"schema_version", "name", "description", "runtime", "governance", "deploy"}
)
LOG_LEVELS = frozenset({"TRACE", "DEBUG", "INFO", "WARN", "ERROR"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_path(name: str) -> Path:
    return _repo_root() / "config" / "environments" / f"{name}.yaml"


def normalize_environment_name(name: str) -> str:
    """Normalize and validate an environment name before path construction."""
    normalized = name.strip().lower() if isinstance(name, str) else ""
    if normalized not in VALID_ENVIRONMENTS:
        raise ValueError(f"Environment {normalized!r} is not one of dev, staging, prod")
    return normalized


def current_environment() -> str:
    """Resolve the active deployment environment from process settings.

    Returns:
        str: String result produced by the operation.
    """
    configured = os.environ.get("ARTEMIS_ENV", DEFAULT_ENVIRONMENT)
    try:
        return normalize_environment_name(configured)
    except ValueError as exc:
        raise ValueError(
            f"ARTEMIS_ENV={configured!r} must be one of dev, staging, prod"
        ) from exc


def _validated_mapping(
    profile: Mapping[str, Any],
    key: str,
    fields: frozenset[str],
    expected_name: str,
) -> Mapping[str, Any]:
    value = profile.get(key)
    if not isinstance(value, Mapping):
        raise TypeError(
            f"Environment {expected_name!r} field {key!r} must be a mapping"
        )
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown:
        raise ValueError(
            f"Environment {expected_name!r} has unknown {key} fields: {sorted(unknown)}"
        )
    if missing:
        raise ValueError(
            f"Environment {expected_name!r} is missing {key} fields: {sorted(missing)}"
        )
    return value


def validate_environment_profile(
    data: Mapping[str, Any], expected_name: str
) -> dict[str, Any]:
    """Validate one policy-only environment profile and return a plain dict."""
    name = normalize_environment_name(expected_name)
    if not isinstance(data, Mapping):
        raise TypeError(f"Environment {name!r} profile must be a mapping")

    unknown = set(data) - PROFILE_KEYS
    missing = PROFILE_KEYS - set(data)
    if unknown:
        raise ValueError(
            f"Environment {name!r} has unknown top-level fields: {sorted(unknown)}"
        )
    if missing:
        raise ValueError(f"Environment {name!r} is missing fields: {sorted(missing)}")
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        raise ValueError(f"Environment {name!r} schema_version must be integer 1")
    if data.get("name") != name:
        raise ValueError(f"Environment {name!r} field 'name' must equal the filename")
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Environment {name!r} description must be non-empty")

    runtime = _validated_mapping(
        data,
        "runtime",
        frozenset({"log_level", "debug", "reload"}),
        name,
    )
    if runtime["log_level"] not in LOG_LEVELS:
        raise ValueError(
            f"Environment {name!r} runtime.log_level must be one of "
            f"{sorted(LOG_LEVELS)}"
        )
    for field in ("debug", "reload"):
        if not isinstance(runtime[field], bool):
            raise TypeError(f"Environment {name!r} runtime.{field} must be a boolean")

    governance = _validated_mapping(
        data,
        "governance",
        frozenset({"strict_atp", "trust_default_level"}),
        name,
    )
    if not isinstance(governance["strict_atp"], bool):
        raise TypeError(f"Environment {name!r} governance.strict_atp must be a boolean")
    trust_level = governance["trust_default_level"]
    if (
        not isinstance(trust_level, int)
        or isinstance(trust_level, bool)
        or not 0 <= trust_level <= 3
    ):
        raise ValueError(
            f"Environment {name!r} governance.trust_default_level must be 0..3"
        )

    deploy = _validated_mapping(
        data,
        "deploy",
        frozenset({"branch", "github_environment"}),
        name,
    )
    for field in ("branch", "github_environment"):
        if deploy[field] != name:
            raise ValueError(f"Environment {name!r} deploy.{field} must equal {name!r}")

    return {
        "schema_version": 1,
        "name": name,
        "description": description.strip(),
        "runtime": dict(runtime),
        "governance": dict(governance),
        "deploy": dict(deploy),
    }


def load_environment(name: str | None = None) -> dict[str, Any]:
    """Load the YAML configuration for the selected deployment environment.

    Args:
        name (str | None): Name of the item, class, or environment to resolve.

    Returns:
        Dict[str, Any]: Dictionary containing the resulting data.
    """
    env = (
        normalize_environment_name(name) if name is not None else current_environment()
    )
    path = _config_path(env)
    if not path.exists():
        raise FileNotFoundError(f"Environment config not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return validate_environment_profile(data, env)
