"""Focused round-trip coverage for the remaining MCP utility seams."""

from __future__ import annotations

import importlib.util
import runpy
import sqlite3
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import src.mcp.config as mcp_config
import src.mcp.hebbian_weights as hebbian_module
import src.mcp.vector_store as vector_module
from src import mcp
from src.mcp.hebbian_weights import HebbianWeightManager
from src.mcp.vector_store import LocalVectorStore


def test_mcp_lazy_export_is_cached_and_dir_is_unique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    imported = SimpleNamespace(LocalVectorStore=sentinel)
    calls: list[tuple[str, str]] = []

    def fake_import(module_name: str, package: str):
        calls.append((module_name, package))
        return imported

    monkeypatch.delitem(mcp.__dict__, "LocalVectorStore", raising=False)
    monkeypatch.setattr(mcp, "import_module", fake_import)

    assert mcp.__getattr__("LocalVectorStore") is sentinel
    assert mcp.LocalVectorStore is sentinel
    assert calls == [(".vector_store", "src.mcp")]

    names = mcp.__dir__()
    assert names == sorted(set(names))
    assert set(mcp.__all__) <= set(names)
    assert names.count("LocalVectorStore") == 1

    with pytest.raises(
        AttributeError, match="module 'src.mcp' has no attribute 'not_exported'"
    ):
        mcp.__getattr__("not_exported")


def test_mcp_package_direct_execution_delegates_to_launch_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_file = Path(mcp.__file__).resolve()
    repo_root = package_file.parents[2]
    observed: dict[str, object] = {}
    fake_launch_main = ModuleType("src.launch.main")

    def fake_main() -> int:
        observed["called"] = True
        observed["path_head"] = sys.path[0]
        return 23

    fake_launch_main.main = fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.launch.main", fake_launch_main)
    monkeypatch.setattr(
        sys,
        "path",
        [entry for entry in sys.path if Path(entry or ".").resolve() != repo_root],
    )

    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(package_file), run_name="__main__")

    assert raised.value.code == 23
    assert observed == {"called": True, "path_head": str(repo_root)}


def test_mcp_config_falls_back_without_dotenv_and_honors_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "dotenv", None)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/tmp/artemis-vault")
    monkeypatch.setenv("AGENT_INPUT_DIR", "Inbox")
    monkeypatch.setenv("AGENT_OUTPUT_DIR", "Outbox")
    monkeypatch.setenv("EXO_BASE_URL", "http://exo.internal:9000")
    monkeypatch.setenv("EXO_MODEL_URL", "http://exo.internal:9000/v1")
    monkeypatch.setenv("EXO_MODEL_ID", "local-model")

    spec = importlib.util.spec_from_file_location(
        "src.mcp._config_without_dotenv", Path(mcp_config.__file__)
    )
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)

    assert loaded.load_dotenv(Path("ignored.env"), override=True) is False
    assert loaded.OBSIDIAN_VAULT_PATH == "/tmp/artemis-vault"
    assert loaded.AGENT_INPUT_DIR == "Inbox"
    assert loaded.AGENT_OUTPUT_DIR == "Outbox"
    assert loaded.EXO_BASE_URL == "http://exo.internal:9000"
    assert loaded.EXO_MODEL_URL == "http://exo.internal:9000/v1"
    assert loaded.EXO_MODEL_ID == "local-model"


def test_get_connections_list_orders_limits_and_computes_success_rates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hebbian_module, "_run_logger", False)
    manager = HebbianWeightManager(db_path=str(tmp_path / "hebbian.db"))

    for _ in range(3):
        manager.strengthen_connection("agent-best", "task-best")
    manager.strengthen_connection("agent-mixed", "task-mixed")
    manager.strengthen_connection("agent-mixed", "task-mixed")
    manager.weaken_connection("agent-mixed", "task-mixed")

    # A cold imported connection is a valid migration state and must not divide
    # by zero while the UI list is being constructed.
    with sqlite3.connect(manager.db_path) as conn:
        conn.execute(
            """
            INSERT INTO node_connections (
                origin_node, target_node, weight, activation_count,
                success_count, failure_count
            ) VALUES (?, ?, ?, 0, 0, 0)
            """,
            ("agent-cold", "task-cold", 0.5),
        )
        conn.commit()

    connections = manager.get_connections_list(limit=10)

    assert [item["origin_node"] for item in connections] == [
        "agent-best",
        "agent-mixed",
        "agent-cold",
    ]
    assert connections[0]["success_rate"] == 1.0
    assert connections[1]["activation_count"] == 3
    assert connections[1]["success_count"] == 2
    assert connections[1]["failure_count"] == 1
    assert connections[1]["success_rate"] == pytest.approx(2 / 3)
    assert connections[2]["success_rate"] == 0.0
    assert manager.get_connections_list(limit=1) == [connections[0]]


def test_vector_upsert_many_consumes_generators_and_replaces_existing_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vector_module, "_run_logger", False)
    store = LocalVectorStore(
        db_path=str(tmp_path / "vectors.db"),
        embedding_fn=lambda text: [float(len(text))],
    )
    consumed: list[str] = []

    def records():
        for record in (
            ("doc-a", "old", None),
            ("doc-b", "second", {"kind": "stable", "decay_score": 0.25}),
            ("doc-a", "replacement", {"kind": "updated"}),
        ):
            consumed.append(record[0])
            yield record

    store.upsert_many(records())
    store.upsert_many(())
    rows = {record.doc_id: record for record in store.fetch_all()}

    assert consumed == ["doc-a", "doc-b", "doc-a"]
    assert store.count() == 2
    assert rows["doc-a"].content == "replacement"
    assert rows["doc-a"].embedding == [11.0]
    assert rows["doc-a"].metadata["kind"] == "updated"
    assert rows["doc-a"].weight == 1.0
    assert rows["doc-a"].archived is False
    assert rows["doc-b"].metadata["kind"] == "stable"
    assert rows["doc-b"].weight == pytest.approx(0.25)
