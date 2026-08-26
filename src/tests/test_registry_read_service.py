"""Contract tests for the read-only agent registry service."""

from __future__ import annotations

import ast
import inspect
import traceback
from collections.abc import Iterator, Mapping, Sequence
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


class _ExplodingGetPort:
    """Port double that exposes whether get failures are sanitized."""

    def get_agent_record(self, name: str) -> Mapping[str, object] | None:
        raise RuntimeError(f"backend exploded for {name}")

    def list_agent_records(self) -> Sequence[Mapping[str, object]]:
        return ()


class _ExplodingListPort:
    """Port double that exposes whether list failures are sanitized."""

    def get_agent_record(self, name: str) -> Mapping[str, object] | None:
        return None

    def list_agent_records(self) -> Sequence[Mapping[str, object]]:
        raise RuntimeError("backend failed at /private/registry-secret.db")


class _SecretRegistryErrorGetPort:
    """Port double that raises the service's error type with an unsafe message."""

    def get_agent_record(self, name: str) -> Mapping[str, object] | None:
        raise RegistryRecordError("port-registry-secret")

    def list_agent_records(self) -> Sequence[Mapping[str, object]]:
        return ()


class _SecretRegistryErrorSequence(list[Mapping[str, object]]):
    """Store sequence that leaks through iteration unless the boundary sanitizes it."""

    def __iter__(self) -> Iterator[Mapping[str, object]]:
        raise RegistryRecordError("iterator-registry-secret")


class _SecretRegistryErrorListPort:
    """Port double returning a hostile list iterator."""

    def get_agent_record(self, name: str) -> Mapping[str, object] | None:
        return None

    def list_agent_records(self) -> Sequence[Mapping[str, object]]:
        return _SecretRegistryErrorSequence()


class _SingleRecordPort:
    """Read port for projection failures that avoids inspecting the record itself."""

    def __init__(self, record: Mapping[str, object]) -> None:
        self._record = record

    def get_agent_record(self, name: str) -> Mapping[str, object] | None:
        return self._record

    def list_agent_records(self) -> Sequence[Mapping[str, object]]:
        return (self._record,)


class _ExplodingRecord(Mapping[str, object]):
    """Canonical-shaped mapping that fails while a public key is extracted."""

    def __getitem__(self, key: str) -> object:
        raise RuntimeError("stored-secret-value")

    def __iter__(self):
        return iter(())

    def __len__(self) -> int:
        return 3


class _ExplodingCapabilities(list[str]):
    """Canonical-shaped capabilities that fail during validation iteration."""

    def __iter__(self):
        raise RuntimeError("stored-capability-secret")


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


def _assert_sanitized_record_error(
    error: pytest.ExceptionInfo[RegistryRecordError], secret: str
) -> None:
    """Assert that a failed read cannot reveal a lower-layer exception."""
    raised = error.value
    rendered = "".join(traceback.format_exception(raised))

    assert str(raised) == "registry record is malformed"
    assert secret not in rendered
    assert raised.__cause__ is None
    assert raised.__suppress_context__ is True


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

    _assert_sanitized_record_error(error, "research")


def test_get_port_failure_does_not_expose_the_caller_name() -> None:
    """A get-port exception must not leak an agent name to a read caller."""
    service = RegistryReadService(_ExplodingGetPort())
    private_name = "caller-private-name"

    with pytest.raises(RegistryRecordError) as error:
        service.get_agent(private_name)

    _assert_sanitized_record_error(error, private_name)


def test_get_capabilities_sanitizes_get_port_failure() -> None:
    """Capabilities reads retain the same failure boundary as agent reads."""
    service = RegistryReadService(_ExplodingGetPort())
    private_name = "capability-private-name"

    with pytest.raises(RegistryRecordError) as error:
        service.get_capabilities(private_name)

    _assert_sanitized_record_error(error, private_name)


def test_list_port_failure_does_not_expose_backend_details() -> None:
    """A list-port exception cannot reveal paths or other backend diagnostics."""
    service = RegistryReadService(_ExplodingListPort())

    with pytest.raises(RegistryRecordError) as error:
        service.list_agents()

    _assert_sanitized_record_error(error, "/private/registry-secret.db")


def test_get_port_registry_error_cannot_supply_a_public_message() -> None:
    """Even a same-class exception from a port is untrusted input."""
    service = RegistryReadService(_SecretRegistryErrorGetPort())

    with pytest.raises(RegistryRecordError) as error:
        service.get_agent("research")

    _assert_sanitized_record_error(error, "port-registry-secret")


def test_list_iterator_registry_error_cannot_supply_a_public_message() -> None:
    """Even a same-class exception from store iteration is untrusted input."""
    service = RegistryReadService(_SecretRegistryErrorListPort())

    with pytest.raises(RegistryRecordError) as error:
        service.list_agents()

    _assert_sanitized_record_error(error, "iterator-registry-secret")


def test_mapping_key_failure_does_not_expose_stored_details() -> None:
    """Record key extraction is inside the same sanitizing error boundary."""
    service = RegistryReadService(_SingleRecordPort(_ExplodingRecord()))

    with pytest.raises(RegistryRecordError) as error:
        service.get_agent("research")

    _assert_sanitized_record_error(error, "stored-secret-value")


def test_capability_iteration_failure_does_not_expose_stored_details() -> None:
    """Capability validation iteration is inside the sanitizing error boundary."""
    record = _record()
    record["capabilities"] = _ExplodingCapabilities(["search"])
    service = RegistryReadService(_SingleRecordPort(record))

    with pytest.raises(RegistryRecordError) as error:
        service.get_agent("research")

    _assert_sanitized_record_error(error, "stored-capability-secret")


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
