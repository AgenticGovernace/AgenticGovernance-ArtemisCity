"""Dependency-injected, read-only projections of registry store records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from .models import RegistryAgentView


class RegistryRecordError(ValueError):
    """A canonical registry record cannot be safely exposed to a read caller."""


class RegistryReadPort(Protocol):
    """The minimal read-only surface required from the canonical registry store."""

    def get_agent_record(self, name: str) -> Mapping[str, object] | None:
        """Return one canonical registry record, if present."""

    def list_agent_records(self) -> Sequence[Mapping[str, object]]:
        """Return canonical registry records in store-defined order."""


class RegistryReadService:
    """Safely project canonical registry records to their public read contract."""

    def __init__(self, port: RegistryReadPort) -> None:
        self._port = port

    def get_agent(self, name: str) -> RegistryAgentView | None:
        """Return one public agent view, or ``None`` if it is absent."""
        self._validate_name(name)
        record = self._port.get_agent_record(name)
        return None if record is None else self._project(record)

    def list_agents(self) -> tuple[RegistryAgentView, ...]:
        """Return public agent views, preserving the store's ordering."""
        return tuple(
            self._project(record) for record in self._port.list_agent_records()
        )

    def get_capabilities(self, name: str) -> tuple[str, ...] | None:
        """Return immutable capabilities for one agent, or ``None`` if absent."""
        agent = self.get_agent(name)
        return None if agent is None else agent.capabilities

    @staticmethod
    def _validate_name(name: str) -> None:
        if type(name) is not str or not name:
            raise ValueError("invalid registry agent name")

    @staticmethod
    def _project(record: Mapping[str, object]) -> RegistryAgentView:
        if not isinstance(record, Mapping):
            raise RegistryRecordError("registry record is malformed")

        try:
            name = record["name"]
            capabilities = record["capabilities"]
            description = record["description"]
        except KeyError as exc:
            raise RegistryRecordError("registry record is malformed") from exc

        if (
            type(name) is not str
            or not name
            or not isinstance(capabilities, (list, tuple))
            or any(
                type(capability) is not str or not capability
                for capability in capabilities
            )
            or (description is not None and type(description) is not str)
        ):
            raise RegistryRecordError("registry record is malformed")

        return RegistryAgentView(
            name=name,
            capabilities=tuple(capabilities),
            description=description,
        )
