"""Contract tests for repository-wide runtime storage resolution."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.runtime_paths import REPO_ROOT, data_dir, data_path, log_path, logs_dir


def test_defaults_are_repo_rooted_when_cwd_changes(tmp_path, monkeypatch):
    """Default data and log paths must never depend on process cwd."""
    monkeypatch.delenv("ARTEMIS_DATA_DIR", raising=False)
    monkeypatch.delenv("ARTEMIS_LOG_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert data_dir() == REPO_ROOT / "data"
    assert logs_dir() == REPO_ROOT / "logs"
    assert data_path("agent_registry.db") == str(REPO_ROOT / "data/agent_registry.db")
    assert log_path("mcp_obsidian.log") == str(REPO_ROOT / "logs/mcp_obsidian.log")


def test_relative_overrides_stay_inside_configured_roots(tmp_path, monkeypatch):
    """Relative umbrella and per-store overrides remain deterministic."""
    monkeypatch.setenv("ARTEMIS_DATA_DIR", "runtime-data")
    monkeypatch.setenv("ARTEMIS_LOG_DIR", "runtime-logs")
    monkeypatch.setenv("ARTEMIS_REGISTRY_DB", "registry/custom.db")
    monkeypatch.chdir(tmp_path)

    assert data_dir() == REPO_ROOT / "runtime-data"
    assert logs_dir() == REPO_ROOT / "runtime-logs"
    assert data_path("agent_registry.db", env_var="ARTEMIS_REGISTRY_DB") == str(
        REPO_ROOT / "runtime-data/registry/custom.db"
    )
    assert log_path("memory_decay") == str(REPO_ROOT / "runtime-logs/memory_decay")


def test_absolute_and_in_memory_overrides_are_preserved(tmp_path):
    """Tests, containers, and SQLite in-memory callers can remain isolated."""
    absolute = tmp_path / "isolated.db"

    assert data_path("default.db", absolute) == str(absolute)
    assert data_path("default.db", ":memory:") == ":memory:"


def test_relative_overrides_cannot_escape_their_runtime_root(monkeypatch):
    """Traversal requires an explicit absolute container/test override."""
    monkeypatch.setenv("ARTEMIS_REGISTRY_DB", "../outside.db")

    with pytest.raises(ValueError, match="must stay within"):
        data_path("agent_registry.db", env_var="ARTEMIS_REGISTRY_DB")


def test_core_stores_share_data_and_log_roots(tmp_path, monkeypatch):
    """Every primary runtime store resolves through the same two roots."""
    runtime_data = tmp_path / "data"
    runtime_logs = tmp_path / "logs"
    monkeypatch.setenv("ARTEMIS_DATA_DIR", str(runtime_data))
    monkeypatch.setenv("ARTEMIS_LOG_DIR", str(runtime_logs))
    for name in (
        "ARTEMIS_REGISTRY_DB",
        "ARTEMIS_HEBBIAN_DB",
        "ARTEMIS_VECTOR_DB",
        "ARTEMIS_TRUST_DB",
        "ARTEMIS_RUN_LOG_DB",
        "ARTEMIS_KERNEL_STATE",
        "ARTEMIS_MEMORY_STORE_DIR",
        "ARTEMIS_GOVERNANCE_DATA",
    ):
        monkeypatch.delenv(name, raising=False)
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    from app.kernel.kernel import Kernel
    from src.integration.agent_registry import AgentRegistryStore
    from src.integration.governance import GovernanceMonitor
    from src.integration.trust_interface import TrustStore
    from src.mcp.hebbian_weights import HebbianWeightManager
    from src.mcp.vector_store import LocalVectorStore
    from src.utils.run_logger import RunLogger

    registry = AgentRegistryStore()
    governance = GovernanceMonitor()
    hebbian = HebbianWeightManager()
    vector = LocalVectorStore()
    trust = TrustStore()
    run_logger = RunLogger(run_id="runtime_path_contract")
    kernel = Kernel()

    assert Path(registry.db_path) == runtime_data / "agent_registry.db"
    assert governance.log_path == runtime_data / "governance_events.jsonl"
    assert Path(hebbian.db_path) == runtime_data / "hebbian_weights.db"
    assert Path(vector.db_path) == runtime_data / "vector_store.db"
    assert trust.db_path == runtime_data / "trust_scores.db"
    assert Path(run_logger.db_path) == runtime_data / "run_logs.db"
    assert run_logger.log_dir == runtime_logs
    assert Path(kernel.state_file) == runtime_data / "state_kernel.json"
    assert Path(kernel.memory.backend.base_path) == runtime_data / "memory_store"


def test_dashboard_api_reads_the_same_data_root_from_any_cwd(tmp_path):
    """FastAPI metrics constants must match the canonical core stores."""
    runtime_data = tmp_path / "shared-data"
    runtime_logs = tmp_path / "shared-logs"
    nested_cwd = tmp_path / "nested/process"
    nested_cwd.mkdir(parents=True)
    env = os.environ.copy()
    env.update(
        {
            "ARTEMIS_DATA_DIR": str(runtime_data),
            "ARTEMIS_LOG_DIR": str(runtime_logs),
            "ARTEMIS_LOG_FILE": str(runtime_logs / "api.log"),
            "PYTHONPATH": str(REPO_ROOT),
        }
    )
    command = (
        "import json; "
        "from app.api import main; "
        "print(json.dumps({"
        "'registry': str(main.AGENT_REGISTRY_DB), "
        "'hebbian': str(main.HEBBIAN_DB), "
        "'vector': str(main.VECTOR_DB), "
        "'runs': str(main.RUN_LOG_DB)"
        "}))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=nested_cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = json.loads(completed.stdout.strip().splitlines()[-1])

    assert paths == {
        "registry": str(runtime_data / "agent_registry.db"),
        "hebbian": str(runtime_data / "hebbian_weights.db"),
        "vector": str(runtime_data / "vector_store.db"),
        "runs": str(runtime_data / "run_logs.db"),
    }
    assert not (nested_cwd / "data").exists()
    assert not (nested_cwd / "logs").exists()


def test_each_run_logger_invocation_gets_a_unique_record(tmp_path):
    """Concurrent or rapid runs must not overwrite one another's log."""
    from src.utils.run_logger import RunLogger

    log_dir = tmp_path / "logs"
    db_path = tmp_path / "data/run_logs.db"
    first = RunLogger(log_dir=str(log_dir), db_path=str(db_path))
    second = RunLogger(log_dir=str(log_dir), db_path=str(db_path))

    assert first.run_id != second.run_id
    assert first.md_path != second.md_path
    assert first.md_path.exists()
    assert second.md_path.exists()
