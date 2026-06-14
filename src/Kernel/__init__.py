"""Compatibility exports for legacy ``src.Kernel`` imports.

The maintained kernel implementation lives under :mod:`app.kernel`.
"""

from app.kernel.agent_router import AgentRouter
from app.kernel.kernel import Kernel
from app.kernel.memory_bus import (
    FileMemoryBackend,
    MemoryBackend,
    MemoryBus,
    VectorMemoryBackend,
)

__all__ = [
    "Kernel",
    "AgentRouter",
    "MemoryBus",
    "MemoryBackend",
    "FileMemoryBackend",
    "VectorMemoryBackend",
]
