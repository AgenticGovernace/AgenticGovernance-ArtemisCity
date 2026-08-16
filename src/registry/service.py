"""Dependency-injected, read-only projections of registry store records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NoReturn, Protocol

from .models import RegistryAgentView


class RegistryRecordError(ValueError):
    """A canonical registry record cannot be safely exposed to a read caller."""


_MALFORMED_RECORD_MESSAGE = "registry record is malformed"


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
        try:
            record = self._port.get_agent_record(name)
        except Exception:  # noqa: BLE001 - sanitize untrusted port failures
            self._raise_malformed_record()
        return None if record is None else self._project(record)

    def list_agents(self) -> tuple[RegistryAgentView, ...]:
        """Return public agent views, preserving the store's ordering."""
        try:
            return tuple(
                self._project(record) for record in self._port.list_agent_records()
            )
        except Exception:  # noqa: BLE001 - sanitize untrusted port failures
            self._raise_malformed_record()

    def get_capabilities(self, name: str) -> tuple[str, ...] | None:
        """Return immutable capabilities for one agent, or ``None`` if absent."""
        agent = self.get_agent(name)
        return None if agent is None else agent.capabilities

    @staticmethod
    def _validate_name(name: str) -> None:
        if type(name) is not str or not name:
            raise ValueError("invalid registry agent name")

    @classmethod
    def _project(cls, record: Mapping[str, object]) -> RegistryAgentView:
        try:
            if not isinstance(record, Mapping):
                cls._raise_malformed_record()
            name = record["name"]
            capabilities = record["capabilities"]
            description = record["description"]
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
                cls._raise_malformed_record()
            return RegistryAgentView(
                name=name,
                capabilities=tuple(capabilities),
                description=description,
            )
        except Exception:  # noqa: BLE001 - sanitize untrusted stored values
            cls._raise_malformed_record()

    @staticmethod
    def _raise_malformed_record() -> NoReturn:
        raise RegistryRecordError(_MALFORMED_RECORD_MESSAGE) from None
