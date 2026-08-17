"""Typed, flat MCP boundary models for the canonical memory service."""

from __future__ import annotations

from artemis_mcp_common.models import AtpEnvelope
from pydantic import BaseModel, ConfigDict, Field


class MemoryMCPModel(BaseModel):
    """Base model for all artemis-memory MCP boundary contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class WriteMemoryInput(MemoryMCPModel):
    """Public write-tool input. Carries no principal, capability, or trust field."""

    namespace: str = Field(min_length=1)
    key: str = Field(min_length=1)
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)
    requested_projections: list[str] = Field(default_factory=list)
    atp: AtpEnvelope


class ReadMemoryInput(MemoryMCPModel):
    """Public read-tool input, governed by ATP like every other tool."""

    namespace: str = Field(min_length=1)
    key: str = Field(min_length=1)
    atp: AtpEnvelope


class SearchMemoryInput(MemoryMCPModel):
    """Public search-tool input with a bounded result count."""

    namespace: str = Field(min_length=1)
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    atp: AtpEnvelope


class GetMemoryStatusInput(MemoryMCPModel):
    """Version-specific status input; never accepts a logical memory ID."""

    namespace: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    atp: AtpEnvelope


class WriteMemoryResult(MemoryMCPModel):
    """Structured write receipt mirroring the domain ``MemoryWriteReceipt``."""

    memory_id: str
    record_id: str
    namespace: str
    key: str
    version: int
    content_sha256: str
    disposition: str
    ledger_state: str
    projection_states: dict[str, str]
    summary: str = Field(min_length=1)


class ReadMemoryResult(MemoryMCPModel):
    """The current exact memory version for one namespace/key."""

    memory_id: str
    record_id: str
    namespace: str
    key: str
    version: int
    content: str
    content_sha256: str
    summary: str = Field(min_length=1)


class SearchMemoryRecord(MemoryMCPModel):
    """One search hit, without full content."""

    memory_id: str
    record_id: str
    namespace: str
    key: str
    version: int
    content_sha256: str


class SearchMemoryResult(MemoryMCPModel):
    """Bounded search results for one namespace."""

    records: list[SearchMemoryRecord]
    summary: str = Field(min_length=1)


class GetMemoryStatusResult(MemoryMCPModel):
    """Projection delivery status for one immutable record version."""

    record_id: str
    namespace: str
    projection_states: dict[str, str]
    summary: str = Field(min_length=1)
