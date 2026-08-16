"""Contract tests for the read-only agent registry service."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from src.agents.base_agent import BaseAgent
from src.integration.agent_registry import AgentRegistryStore, AgentScore
from src.registry.models import RegistryAgentView
from src.registry.service import (
    RegistryReadPort,
    RegistryReadService,
    RegistryRecordError,
)


class _FakePort:
    """In-memory port that rejects any surface beyond the read contract."""

    def __init__(
        self,
        records: Sequence[Mapping[str, object]],
    ) -> None:
        self.records = list(records)
        self.get_calls: list[str] = []
        self.list_calls = 0

    def get_agent_record(self, name: str) -> Mapping[str, object] | None:
        self.get_calls.append(name)
        return next((record for record in self.records if record["name"] == name), None)

    def list_agent_records(self) -> Sequence[Mapping[str, object]]:
        self.list_calls += 1
        return self.records

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected port access: {name}")


class _StoredAgent(BaseAgent):
    def perform_task(self, task_context: dict) -> dict:
        return {"status": "success", "summary": "stored"}


def _record(name: str = "research") -> dict[str, object]:
    return {
        "name": name,
        "capabilities": ["search", "summarize"],
        "description": "Finds and summarizes information.",
        "trust_score": 1.0,
        "status": "active",
        "violation_count": 0,
        "execution_count": 42,
        "hebbian_weight": 0.75,
        "routing_intelligence": 0.9,
    }


def test_get_agent_projects_only_the_public_canonical_fields() -> None:
    """A change that returns a canonical row directly must fail this test."""
    port = _FakePort([_record()])

    result = RegistryReadService(port).get_agent("research")

    assert result == RegistryAgentView(
        name="research",
        capabilities=("search", "summarize"),
        description="Finds and summarizes information.",
    )
    assert result.model_dump() == {
        "name": "research",
        "capabilities": ("search", "summarize"),
        "description": "Finds and summarizes information.",
    }
    assert port.get_calls == ["research"]
    assert port.list_calls == 0


def test_missing_agent_stays_none_and_capabilities_are_immutable() -> None:
    """A missing canonical row remains absent rather than becoming an empty view."""
    port = _FakePort([])
    service = RegistryReadService(port)

    assert service.get_agent("missing") is None
    assert service.get_capabilities("missing") is None
    assert port.get_calls == ["missing", "missing"]


def test_list_preserves_store_order_and_returns_an_immutable_tuple() -> None:
    """A sorting or mutable-list regression is visible to registry clients."""
    port = _FakePort([_record("zeta"), _record("alpha")])

    result = RegistryReadService(port).list_agents()

    assert tuple(agent.name for agent in result) == ("zeta", "alpha")
    assert isinstance(result, tuple)
    assert all(isinstance(agent.capabilities, tuple) for agent in result)
    assert port.get_calls == []
    assert port.list_calls == 1


def test_projection_copies_mutable_records_and_capability_lists() -> None:
    """Later raw-store mutations cannot change an already returned public view."""
    raw_record = _record()
    port = _FakePort([raw_record])

    result = RegistryReadService(port).get_agent("research")
    assert result is not None
    raw_record["name"] = "changed"
    capabilities = raw_record["capabilities"]
    assert isinstance(capabilities, list)
    capabilities.append("mutated")

    assert result.name == "research"
    assert result.capabilities == ("search", "summarize")


@pytest.mark.parametrize("name", ["", 1, True])
def test_invalid_caller_name_fails_with_a_static_sanitized_error(name: object) -> None:
    """Invalid caller names never reach the port or appear in an error message."""
    port = _FakePort([])
    service = RegistryReadService(port)

    with pytest.raises(ValueError) as error:
        service.get_agent(name)  # type: ignore[arg-type]

    assert str(error.value) == "invalid registry agent name"
    if name:
        assert str(name) not in str(error.value)
    assert port.get_calls == []


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"name": "research", "capabilities": [], "description": 1},
        {"name": "research", "capabilities": [1], "description": None},
        {"name": "research", "capabilities": "search", "description": None},
        {"name": "", "capabilities": [], "description": None},
    ],
)
def test_malformed_canonical_records_fail_closed_with_a_static_error(
    record: Mapping[str, object],
) -> None:
    """Malformed stored data is never coerced or exposed to a caller."""
    service = RegistryReadService(_FakePort([record]))

    with pytest.raises(RegistryRecordError) as error:
        service.list_agents()

    assert str(error.value) == "registry record is malformed"


def test_real_store_adapter_preserves_sqlite_order_and_nullable_description(
    tmp_path,
) -> None:
    """The canonical SQLite store works directly as the narrow read port."""
    store = AgentRegistryStore(db_path=str(tmp_path / "registry.db"))
    default_score = AgentScore(alignment=0.5, accuracy=0.5, efficiency=0.5)
    store.upsert_agent(_StoredAgent("zeta", capabilities=["z-cap"]), default_score)
    store.upsert_agent(_StoredAgent("alpha", capabilities=["a-cap"]), default_score)

    result = RegistryReadService(store).list_agents()

    assert tuple(agent.name for agent in result) == ("alpha", "zeta")
    assert result[0].capabilities == ("a-cap",)
    assert result[0].description is None


def test_read_service_has_no_forbidden_dependency_imports_or_constructor_io(
    capsys,
) -> None:
    """This core stays dependency-injected and does no work until a read is requested."""
    import src.registry.service as service_module

    source = Path(service_module.__file__).read_text(encoding="utf-8")
    imported_modules = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }
    forbidden_roots = {
        "src.auth",
        "src.mcp",
        "src.provenance",
        "src.routing",
        "src.integration",
        "sqlite3",
        "os",
        "pathlib",
    }

    port = _FakePort([])
    RegistryReadService(port)

    assert not any(
        imported == root or imported.startswith(f"{root}.")
        for imported in imported_modules
        for root in forbidden_roots
    )
    assert port.get_calls == []
    assert port.list_calls == 0
    assert capsys.readouterr().out == ""
    assert list(inspect.signature(RegistryReadService).parameters) == ["port"]
    assert set(RegistryReadPort.__dict__) >= {"get_agent_record", "list_agent_records"}
