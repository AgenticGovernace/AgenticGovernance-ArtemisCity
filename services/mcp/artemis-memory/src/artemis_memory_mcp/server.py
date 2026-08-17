"""The artemis-memory MCP server: governed tools over the canonical MemoryService."""

from __future__ import annotations

from collections.abc import Callable

import anyio.to_thread
from artemis_mcp_common.gate import GovernanceDenied, GovernedGate
from artemis_mcp_common.models import AtpEnvelope, ServicePrincipal
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from src.memory.models import (
    MemoryIdempotencyConflict,
    MemoryLedgerUnavailable,
    MemoryNamespaceConflict,
    MemoryValidationError,
    MemoryWriteCommand,
)
from src.memory.service import MemoryService

from .models import (
    GetMemoryStatusInput,
    GetMemoryStatusResult,
    ReadMemoryInput,
    ReadMemoryResult,
    SearchMemoryInput,
    SearchMemoryRecord,
    SearchMemoryResult,
    WriteMemoryInput,
    WriteMemoryResult,
)

_WRITE_CAPABILITY = "memory:write"
_READ_CAPABILITY = "memory:read"

_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

_DOMAIN_ERRORS = (
    MemoryValidationError,
    MemoryLedgerUnavailable,
    MemoryIdempotencyConflict,
    MemoryNamespaceConflict,
)

PrincipalProvider = Callable[[], ServicePrincipal]


def _namespace_scope(namespace: str) -> str:
    return f"memory:namespace:{namespace}"


def _controlled_error(exc: Exception) -> ToolError:
    """Translate a governance or domain exception into a sanitized tool error."""
    return ToolError(str(exc))


def create_memory_server(
    *,
    memory_service: MemoryService,
    gate: GovernedGate,
    principal_provider: PrincipalProvider,
    auth: AuthSettings | None = None,
    token_verifier: TokenVerifier | None = None,
) -> MCPServer:
    """Build the governed artemis-memory MCP server.

    ``auth`` and ``token_verifier`` are passed straight to the ``MCPServer``
    constructor; handlers never simulate transport authentication themselves.
    """
    if (auth is None) != (token_verifier is None):
        raise ValueError("auth and token_verifier must be supplied together")

    mcp_server = MCPServer(
        "artemis-memory",
        title="Artemis Memory",
        description=(
            "Governed write, read, search, and status tools over the "
            "canonical Artemis City memory ledger."
        ),
        version="0.1.0",
        auth=auth,
        token_verifier=token_verifier,
    )

    @mcp_server.tool(
        name="write-memory",
        title="Write Memory",
        description="Write one canonical memory version and deliver requested projections.",
        annotations=_WRITE_ANNOTATIONS,
        structured_output=True,
    )
    async def write_memory(
        namespace: str,
        key: str,
        content: str,
        idempotency_key: str,
        atp: AtpEnvelope,
        metadata: dict[str, object] | None = None,
        requested_projections: list[str] | None = None,
    ) -> WriteMemoryResult:
        request = WriteMemoryInput(
            namespace=namespace,
            key=key,
            content=content,
            metadata=metadata or {},
            idempotency_key=idempotency_key,
            requested_projections=requested_projections or [],
            atp=atp,
        )
        principal = principal_provider()
        try:
            context = gate.authorize(
                principal,
                request.atp,
                _WRITE_CAPABILITY,
                required_scope=_namespace_scope(request.namespace),
            )
        except GovernanceDenied as exc:
            raise _controlled_error(exc) from exc

        command = MemoryWriteCommand(
            namespace=request.namespace,
            key=request.key,
            content=request.content,
            metadata=request.metadata,
            idempotency_key=request.idempotency_key,
            principal_id=context.principal.principal_id,
            parent_provenance_id=context.atp.parent_provenance_id,
            requested_projections=tuple(request.requested_projections),
        )
        try:
            receipt = await anyio.to_thread.run_sync(memory_service.write, command)
        except _DOMAIN_ERRORS as exc:
            raise _controlled_error(exc) from exc

        return WriteMemoryResult(
            memory_id=receipt.record.memory_id,
            record_id=receipt.record.record_id,
            namespace=receipt.record.namespace,
            key=receipt.record.key,
            version=receipt.record.version,
            content_sha256=receipt.record.content_sha256,
            disposition=receipt.disposition.value,
            ledger_state=receipt.ledger_state.value,
            projection_states={
                name: state.value for name, state in receipt.projection_states.items()
            },
            summary=receipt.summary,
        )

    @mcp_server.tool(
        name="read-memory",
        title="Read Memory",
        description="Read the current version of one governed memory.",
        annotations=_READ_ANNOTATIONS,
        structured_output=True,
    )
    async def read_memory(
        namespace: str, key: str, atp: AtpEnvelope
    ) -> ReadMemoryResult:
        request = ReadMemoryInput(namespace=namespace, key=key, atp=atp)
        principal = principal_provider()
        try:
            gate.authorize(
                principal,
                request.atp,
                _READ_CAPABILITY,
                required_scope=_namespace_scope(request.namespace),
            )
        except GovernanceDenied as exc:
            raise _controlled_error(exc) from exc

        try:
            record = await anyio.to_thread.run_sync(
                memory_service.read, request.namespace, request.key
            )
        except MemoryValidationError as exc:
            raise _controlled_error(exc) from exc
        if record is None:
            raise ToolError(
                f"no memory found for namespace={request.namespace} key={request.key}"
            )
        return ReadMemoryResult(
            memory_id=record.memory_id,
            record_id=record.record_id,
            namespace=record.namespace,
            key=record.key,
            version=record.version,
            content=record.content,
            content_sha256=record.content_sha256,
            summary=f"Memory {record.memory_id} version {record.version} read.",
        )

    @mcp_server.tool(
        name="search-memory",
        title="Search Memory",
        description="Search current memories within one governed namespace.",
        annotations=_READ_ANNOTATIONS,
        structured_output=True,
    )
    async def search_memory(
        namespace: str, query: str, atp: AtpEnvelope, limit: int = 10
    ) -> SearchMemoryResult:
        request = SearchMemoryInput(
            namespace=namespace, query=query, limit=limit, atp=atp
        )
        principal = principal_provider()
        try:
            gate.authorize(
                principal,
                request.atp,
                _READ_CAPABILITY,
                required_scope=_namespace_scope(request.namespace),
            )
        except GovernanceDenied as exc:
            raise _controlled_error(exc) from exc

        try:
            records = await anyio.to_thread.run_sync(
                memory_service.search, request.namespace, request.query, request.limit
            )
        except MemoryValidationError as exc:
            raise _controlled_error(exc) from exc

        return SearchMemoryResult(
            records=[
                SearchMemoryRecord(
                    memory_id=record.memory_id,
                    record_id=record.record_id,
                    namespace=record.namespace,
                    key=record.key,
                    version=record.version,
                    content_sha256=record.content_sha256,
                )
                for record in records
            ],
            summary=(
                f"{len(records)} memory record(s) matched "
                f"'{request.query}' in {request.namespace}."
            ),
        )

    @mcp_server.tool(
        name="get-memory-status",
        title="Get Memory Status",
        description="Return version-specific projection status for one memory record.",
        annotations=_READ_ANNOTATIONS,
        structured_output=True,
    )
    async def get_memory_status(
        namespace: str, record_id: str, atp: AtpEnvelope
    ) -> GetMemoryStatusResult:
        request = GetMemoryStatusInput(
            namespace=namespace, record_id=record_id, atp=atp
        )
        principal = principal_provider()
        try:
            gate.authorize(
                principal,
                request.atp,
                _READ_CAPABILITY,
                required_scope=_namespace_scope(request.namespace),
            )
        except GovernanceDenied as exc:
            raise _controlled_error(exc) from exc

        try:
            states = await anyio.to_thread.run_sync(
                memory_service.projection_status,
                request.namespace,
                request.record_id,
            )
        except MemoryValidationError as exc:
            raise _controlled_error(exc) from exc
        if states is None:
            raise ToolError(
                f"no memory record {request.record_id} found in "
                f"namespace={request.namespace}"
            )
        return GetMemoryStatusResult(
            record_id=request.record_id,
            namespace=request.namespace,
            projection_states={name: state.value for name, state in states.items()},
            summary=f"Record {request.record_id} has {len(states)} tracked projection(s).",
        )

    return mcp_server
