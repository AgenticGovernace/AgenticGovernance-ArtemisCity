"""Compatibility wrapper for ``memory.integration.context_loader``.

Canonical implementation lives in ``src.integration.context_loader``.
"""

from src.integration.context_loader import ContextEntry, ContextLoader

__all__ = ["ContextLoader", "ContextEntry"]
