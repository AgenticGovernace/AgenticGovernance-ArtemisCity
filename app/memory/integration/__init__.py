"""Compatibility exports for legacy ``memory.integration`` imports."""

from src.integration import (
    ContextEntry,
    ContextLoader,
    MailPacket,
    MCPOperation,
    MCPResponse,
    MemoryClient,
    PostOffice,
    TrustInterface,
    TrustLevel,
    TrustScore,
    get_post_office,
    get_trust_interface,
)

__all__ = [
    "MemoryClient",
    "MCPResponse",
    "MCPOperation",
    "TrustInterface",
    "TrustScore",
    "TrustLevel",
    "get_trust_interface",
    "ContextLoader",
    "ContextEntry",
    "PostOffice",
    "MailPacket",
    "get_post_office",
]
