"""Coverage and wiring tests for small foundational modules.

These checks intentionally exercise compatibility entry points and declarative
type contracts that otherwise appear as zero-function rows in coverage.py.
"""

from __future__ import annotations

import importlib

import pytest

from src.integration.agent_types import TaskContext, TaskResult
from src.utils import environments


def test_shared_task_contracts_are_runtime_available() -> None:
    """Canonical TypedDict contracts should remain importable for typed clients."""
    assert TaskContext.__required_keys__ == frozenset()
    assert TaskResult.__optional_keys__ >= {"status", "summary", "error"}


@pytest.mark.parametrize(
    ("module_name", "export_name", "canonical_module"),
    [
        ("src.integration.run_logger", "RunLogger", "src.utils.run_logger"),
        (
            "src.memory.integration.context_loader",
            "ContextLoader",
            "src.integration.context_loader",
        ),
        (
            "src.memory.integration.memory_client",
            "MemoryClient",
            "src.integration.memory_client",
        ),
        (
            "src.memory.integration.trust_interface",
            "TrustInterface",
            "src.integration.trust_interface",
        ),
    ],
)
def test_compatibility_modules_reexport_canonical_implementations(
    module_name: str,
    export_name: str,
    canonical_module: str,
) -> None:
    """Legacy package paths must not carry independent implementations."""
    module = importlib.import_module(module_name)

    assert getattr(module, export_name).__module__ == canonical_module


@pytest.mark.parametrize(
    ("module_name", "main_module"),
    [
        ("src.interface.artemis_cli", "app.kernel.artemis_cli"),
        ("src.mcp.__main__", "src.launch.main"),
    ],
)
def test_compatibility_entrypoints_resolve_to_maintained_main(
    module_name: str,
    main_module: str,
) -> None:
    """Thin CLI entry points should delegate to their documented implementation."""
    module = importlib.import_module(module_name)

    assert module.main.__module__ == main_module


def test_current_environment_defaults_and_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment selection should be predictable and case-insensitive."""
    monkeypatch.delenv("ARTEMIS_ENV", raising=False)
    assert environments.current_environment() == "dev"

    monkeypatch.setenv("ARTEMIS_ENV", "  STAGING ")
    assert environments.current_environment() == "staging"


def test_environment_config_path_is_repo_relative() -> None:
    """Deployment configuration discovery should stay anchored to the checkout."""
    root = environments._repo_root()

    assert root.name in ("Artemis_City", "app")
    assert environments._config_path("prod") == root / "config/environments/prod.yaml"


def test_legacy_kernel_package_reexports_maintained_classes() -> None:
    """The case-sensitive legacy package must not fork kernel implementations."""
    legacy = importlib.import_module("src.Kernel")

    assert legacy.Kernel.__module__ == "app.kernel.kernel"
    assert legacy.MemoryBus.__module__ == "app.kernel.memory_bus"


def test_current_environment_rejects_unknown_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo must fail closed instead of silently loading development config."""
    monkeypatch.setenv("ARTEMIS_ENV", "production")

    with pytest.raises(ValueError, match="ARTEMIS_ENV='production'"):
        environments.current_environment()


def test_load_environment_reads_explicit_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit environments should load the selected YAML document."""
    config_path = tmp_path / "staging.yaml"
    config_path.write_text("environment: staging\nfeature:\n  enabled: true\n")
    monkeypatch.setattr(environments, "_config_path", lambda _name: config_path)

    assert environments.load_environment("staging") == {
        "environment": "staging",
        "feature": {"enabled": True},
    }


def test_load_environment_returns_empty_mapping_for_empty_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty but present configuration file should have a stable shape."""
    config_path = tmp_path / "dev.yaml"
    config_path.write_text("")
    monkeypatch.setattr(environments, "_config_path", lambda _name: config_path)

    assert environments.load_environment("dev") == {}


def test_load_environment_reports_missing_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing deployment configuration must include its resolved path."""
    missing = tmp_path / "prod.yaml"
    monkeypatch.setattr(environments, "_config_path", lambda _name: missing)

    with pytest.raises(FileNotFoundError, match=str(missing)):
        environments.load_environment("prod")
