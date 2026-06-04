"""Environment configuration loader for Artemis City.

The active environment is selected via the ``ARTEMIS_ENV`` variable
(``dev``, ``staging``, ``prod``). Each environment maps to a YAML file in
``config/environments/`` and a same-named long-lived git branch.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

VALID_ENVIRONMENTS = ("dev", "staging", "prod")
DEFAULT_ENVIRONMENT = "dev"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_path(name: str) -> Path:
    return _repo_root() / "config" / "environments" / f"{name}.yaml"


def current_environment() -> str:
    """Resolve the active deployment environment from process settings.
    
    Returns:
        str: String result produced by the operation.
    """
    name = os.environ.get("ARTEMIS_ENV", DEFAULT_ENVIRONMENT).strip().lower()
    if name not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"ARTEMIS_ENV={name!r} is not one of {VALID_ENVIRONMENTS}"
        )
    return name


def load_environment(name: str | None = None) -> Dict[str, Any]:
    """Load the YAML configuration for the selected deployment environment.
    
    Args:
        name (str | None): Name of the item, class, or environment to resolve.
    
    Returns:
        Dict[str, Any]: Dictionary containing the resulting data.
    """
    env = name or current_environment()
    path = _config_path(env)
    if not path.exists():
        raise FileNotFoundError(f"Environment config not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
