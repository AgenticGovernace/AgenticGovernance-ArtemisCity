"""Memory integration package exports for Artemis City.

Exports are resolved lazily so importing a focused submodule such as
``src.integration.agent_registry`` does not pull in memory clients, agents, or
optional HTTP dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context_loader import ContextEntry, ContextLoader
    from .memory_client import (MCPOperation, MCPResponse,  # noqa: F401
                                MemoryClient)
    from .postal_service import MailPacket, PostOffice, get_post_office
    from .trust_interface import (TrustInterface, TrustLevel, TrustScore,
                                  get_trust_interface)

_LAZY_EXPORTS = {
    "MemoryClient": ".memory_client",
    "MCPResponse": ".memory_client",
    "MCPOperation": ".memory_client",
    "TrustInterface": ".trust_interface",
    "TrustScore": ".trust_interface",
    "TrustLevel": ".trust_interface",
    "get_trust_interface": ".trust_interface",
    "ContextLoader": ".context_loader",
    "ContextEntry": ".context_loader",
    "PostOffice": ".postal_service",
    "MailPacket": ".postal_service",
    "get_post_office": ".postal_service",
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(_LAZY_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
