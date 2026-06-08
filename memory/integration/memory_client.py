"""Compatibility wrapper for ``memory.integration.memory_client``."""

from src.integration.memory_client import (MCPOperation, MCPResponse,
                                           MemoryClient)

__all__ = ["MemoryClient", "MCPResponse", "MCPOperation"]
