"""Real-client MCP contract tests for the artemis-memory server."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from artemis_mcp_common.gate import GovernedGate
from artemis_mcp_common.models import ServicePrincipal
from artemis_memory_mcp.server import create_memory_server

from mcp import Client
from src.memory.models import (
    ClaimDisposition,
    LedgerWrite,
    MemoryRecord,
    ProjectionState,
    WriteDisposition,
)
from src.memory.service import MemoryService


class _FakeClaim:
    def __init__(self, record, target, disposition, store):
        self.record = record
        self.target = target
        self.disposition = disposition
        self._store = store

    def mark_succeeded(self):
        self._store.states[(self.record.record_id, self.target)] = (
            ProjectionState.SUCCEEDED
        )

    def mark_failed(self, error_code):
        self._store.states[(self.record.record_id, self.target)] = (
            ProjectionState.FAILED
        )

    def mark_skipped(self):
        self._store.states[(self.record.record_id, self.target)] = (
            ProjectionState.SKIPPED
        )


class FakeMemoryLedger:
    """Minimal in-memory ``MemoryLedger`` test double for MCP contract tests."""

    def __init__(self):
        self.heads: dict[tuple[str, str], MemoryRecord] = {}
        self.records: dict[str, MemoryRecord] = {}
        self.idempotency: dict[tuple[str, str], str] = {}
        self.states: dict[tuple[str, str], ProjectionState] = {}
        self._counter = 0

    def write_version(self, command) -> LedgerWrite:
        idem_key = (command.namespace, command.idempotency_key)
        existing_record_id = self.idempotency.get(idem_key)
        if existing_record_id is not None:
            record = self.records[existing_record_id]
            states = {
                target: self.states.get(
                    (record.record_id, target), ProjectionState.PENDING
                )
                for target in command.requested_projections
            }
            return LedgerWrite(
                record=record,
                disposition=WriteDisposition.REPLAYED,
                projection_states=states,
                projection_event_ids={
                    t: f"evt-{record.record_id}-{t}"
                    for t in command.requested_projections
                },
            )

        head = self.heads.get((command.namespace, command.key))
        version = (head.version + 1) if head else 1
        self._counter += 1
        record_id = f"rec-{self._counter}"
        record = MemoryRecord(
            record_id=record_id,
            memory_id=head.memory_id if head else f"mem-{self._counter}",
            namespace=command.namespace,
            key=command.key,
            projection_path=command.projection_path,
            version=version,
            content=command.content,
            content_sha256=hashlib.sha256(command.content.encode()).hexdigest(),
            metadata=command.metadata,
            idempotency_key=command.idempotency_key,
            principal_id=command.principal_id,
            parent_provenance_id=command.parent_provenance_id,
            completion_provenance_id=f"prov-child-{record_id}",
            created_at=datetime.now(UTC),
        )
        self.records[record_id] = record
        self.heads[(command.namespace, command.key)] = record
        self.idempotency[idem_key] = record_id
        for target in command.requested_projections:
            self.states[(record_id, target)] = ProjectionState.PENDING
        states = {
            target: ProjectionState.PENDING for target in command.requested_projections
        }
        return LedgerWrite(
            record=record,
            disposition=WriteDisposition.CREATED,
            projection_states=states,
            projection_event_ids={
                t: f"evt-{record_id}-{t}" for t in command.requested_projections
            },
        )

    @contextmanager
    def claim_projection(self, record_id, projection):
        record = self.records[record_id]
        head = self.heads.get((record.namespace, record.key))
        is_current = head is not None and head.record_id == record_id
        state = self.states.get((record_id, projection), ProjectionState.PENDING)
        if not is_current:
            disposition = ClaimDisposition.SUPERSEDED
        elif state in (ProjectionState.PENDING, ProjectionState.FAILED):
            disposition = ClaimDisposition.DELIVER
        else:
            disposition = ClaimDisposition.TERMINAL
        yield _FakeClaim(record, projection, disposition, self)

    def read(self, namespace, key):
        return self.heads.get((namespace, key))

    def search(self, namespace, query, limit):
        hits = [
            record
            for (ns, _key), record in self.heads.items()
            if ns == namespace and query.lower() in record.content.lower()
        ]
        return hits[:limit]

    def projection_status(self, namespace, record_id):
        record = self.records.get(record_id)
        if record is None or record.namespace != namespace:
            return None
        return {
            target: state
            for (rid, target), state in self.states.items()
            if rid == record_id
        }


class FakeProjection:
    def __init__(self, name):
        self.name = name
        self.records = []

    def project(self, record):
        self.records.append(record)


def _writer_principal() -> ServicePrincipal:
    return ServicePrincipal(
        principal_id="writer",
        capabilities={
            "memory:write",
            "memory:read",
            "memory:namespace:reviewed",
        },
    )


def _write_atp() -> dict:
    return {
        "mode": "Commit",
        "context": "Store the reviewed note",
        "action_type": "Execute",
        "target_zone": "memory/reviewed",
        "parent_provenance_id": "prov-root",
    }


def _server(principal: ServicePrincipal | None = None):
    ledger = FakeMemoryLedger()
    obsidian = FakeProjection("obsidian")
    service = MemoryService(ledger, [obsidian])
    resolved_principal = principal or _writer_principal()
    server = create_memory_server(
        memory_service=service,
        gate=GovernedGate(),
        principal_provider=lambda: resolved_principal,
    )
    return server, ledger, obsidian


@pytest.mark.asyncio
async def test_tool_list_exposes_exact_governed_contract() -> None:
    server, _, _ = _server()
    async with Client(server) as client:
        listed = await client.list_tools()
        resources = await client.list_resources()

    names = {tool.name for tool in listed.tools}
    assert names == {
        "write-memory",
        "read-memory",
        "search-memory",
        "get-memory-status",
    }
    for tool in listed.tools:
        assert tool.input_schema
        assert tool.output_schema
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is not None
        assert tool.annotations.destructive_hint is not None
        assert tool.annotations.idempotent_hint is not None
        assert tool.annotations.open_world_hint is not None
    assert resources.resources == []


@pytest.mark.asyncio
async def test_write_memory_returns_structured_receipt() -> None:
    server, _, _ = _server()
    async with Client(server) as client:
        result = await client.call_tool(
            "write-memory",
            {
                "namespace": "reviewed",
                "key": "daily/brief",
                "content": "hello world",
                "idempotency_key": "idem-1",
                "atp": _write_atp(),
                "requested_projections": ["obsidian"],
            },
        )

    assert result.is_error is False
    data = result.structured_content
    assert data["version"] == 1
    assert data["disposition"] == "created"
    assert data["ledger_state"] == "succeeded"
    assert data["projection_states"] == {"obsidian": "succeeded"}
    assert len(data["content_sha256"]) == 64


@pytest.mark.asyncio
async def test_write_memory_denied_without_write_capability() -> None:
    reader = ServicePrincipal(
        principal_id="reader",
        capabilities={"memory:read", "memory:namespace:reviewed"},
    )
    server, ledger, _ = _server(reader)
    async with Client(server) as client:
        result = await client.call_tool(
            "write-memory",
            {
                "namespace": "reviewed",
                "key": "daily/brief",
                "content": "hello world",
                "idempotency_key": "idem-1",
                "atp": _write_atp(),
            },
        )

    assert result.is_error is True
    assert "memory:write" in result.content[0].text
    assert ledger.heads == {}


@pytest.mark.asyncio
async def test_write_memory_denied_for_a_namespace_outside_the_grant() -> None:
    principal = ServicePrincipal(
        principal_id="writer",
        capabilities={"memory:write", "memory:namespace:reviewed"},
    )
    server, ledger, _ = _server(principal)
    async with Client(server) as client:
        result = await client.call_tool(
            "write-memory",
            {
                "namespace": "private",
                "key": "daily/brief",
                "content": "hello world",
                "idempotency_key": "idem-1",
                "atp": {
                    "mode": "Commit",
                    "context": "Store the private note",
                    "action_type": "Execute",
                    "target_zone": "memory/private",
                    "parent_provenance_id": "prov-root",
                },
            },
        )

    assert result.is_error is True
    assert "memory:namespace:private" in result.content[0].text
    assert ledger.heads == {}


@pytest.mark.asyncio
async def test_read_search_and_status_are_governed_end_to_end() -> None:
    server, _, _ = _server()
    read_atp = {
        "mode": "Commit",
        "context": "Read the reviewed note",
        "action_type": "Execute",
        "target_zone": "memory/reviewed",
        "parent_provenance_id": "prov-root",
    }
    async with Client(server) as client:
        write_result = await client.call_tool(
            "write-memory",
            {
                "namespace": "reviewed",
                "key": "daily/brief",
                "content": "hello world",
                "idempotency_key": "idem-1",
                "atp": _write_atp(),
            },
        )
        record_id = write_result.structured_content["record_id"]

        read_result = await client.call_tool(
            "read-memory",
            {"namespace": "reviewed", "key": "daily/brief", "atp": read_atp},
        )
        search_result = await client.call_tool(
            "search-memory",
            {"namespace": "reviewed", "query": "hello", "atp": read_atp},
        )
        status_result = await client.call_tool(
            "get-memory-status",
            {"namespace": "reviewed", "record_id": record_id, "atp": read_atp},
        )
        missing_status = await client.call_tool(
            "get-memory-status",
            {
                "namespace": "reviewed",
                "record_id": "rec-does-not-exist",
                "atp": read_atp,
            },
        )

    assert read_result.is_error is False
    assert read_result.structured_content["content"] == "hello world"
    assert search_result.is_error is False
    assert len(search_result.structured_content["records"]) == 1
    assert status_result.is_error is False
    assert status_result.structured_content["record_id"] == record_id
    assert missing_status.is_error is True


@pytest.mark.asyncio
async def test_read_memory_denied_without_namespace_scope() -> None:
    principal = ServicePrincipal(
        principal_id="reader",
        capabilities={"memory:read", "memory:namespace:other"},
    )
    server, _, _ = _server(principal)
    async with Client(server) as client:
        result = await client.call_tool(
            "read-memory",
            {
                "namespace": "reviewed",
                "key": "daily/brief",
                "atp": {
                    "mode": "Commit",
                    "context": "Read the reviewed note",
                    "action_type": "Execute",
                    "target_zone": "memory/reviewed",
                    "parent_provenance_id": "prov-root",
                },
            },
        )

    assert result.is_error is True
    assert "memory:namespace:reviewed" in result.content[0].text
