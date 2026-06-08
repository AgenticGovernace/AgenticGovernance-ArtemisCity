"""Compatibility exports for legacy ``memory.integration`` imports.

The active implementation lives in ``src.integration``. Re-exporting those
symbols here preserves the documented import path while keeping one source of
truth for memory integration behavior.
"""

from src.integration import (ContextEntry, ContextLoader, MailPacket,
                             MCPOperation, MCPResponse, MemoryClient,
                             PostOffice, TrustInterface, TrustLevel,
                             TrustScore, get_post_office, get_trust_interface)

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
