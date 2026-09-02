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
    "ContextEntry",
    "ContextLoader",
    "MCPOperation",
    "MCPResponse",
    "MailPacket",
    "MemoryClient",
    "PostOffice",
    "TrustInterface",
    "TrustLevel",
    "TrustScore",
    "get_post_office",
    "get_trust_interface",
]
