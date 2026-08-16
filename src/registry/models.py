"""Typed public views for read-only registry operations."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmptyStrictString = Annotated[str, StringConstraints(strict=True, min_length=1)]


class RegistryAgentView(BaseModel):
    """The public, immutable projection of one canonical registry record."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: NonEmptyStrictString
    capabilities: tuple[NonEmptyStrictString, ...]
    description: str | None
