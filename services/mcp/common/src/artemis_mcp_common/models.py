"""Strict data contracts shared by Artemis City MCP transports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictInput(BaseModel):
    """Base model that rejects unrecognized contract fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AtpEnvelope(StrictInput):
    """Validated ATP request metadata."""

    mode: str = Field(min_length=1)
    context: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    target_zone: str = Field(min_length=1)
    parent_provenance_id: str = Field(min_length=1)


class ServicePrincipal(StrictInput):
    """Identifies the service caller and its granted capabilities."""

    principal_id: str = Field(min_length=1)
    capabilities: set[str]
    transport: Literal["stdio", "http"] = "stdio"

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, values: set[str]) -> set[str]:
        """Normalize capability names and reject an empty grant set."""
        normalized = {value.strip() for value in values if value.strip()}
        if not normalized:
            raise ValueError("at least one capability is required")
        return normalized


class GovernedContext(StrictInput):
    """The validated request context used by governed MCP services."""

    principal: ServicePrincipal
    atp: AtpEnvelope
    capability: str
    accepted_at: datetime
