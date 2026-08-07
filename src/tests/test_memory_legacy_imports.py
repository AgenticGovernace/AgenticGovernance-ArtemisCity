"""Regression tests for legacy memory package import paths."""

from memory.integration import ContextLoader, MCPOperation, MemoryClient
from memory.integration.context_loader import \
    ContextLoader as SubmoduleContextLoader
from memory.integration.memory_client import \
    MemoryClient as SubmoduleMemoryClient
from memory.integration.trust_interface import \
    TrustInterface as SubmoduleTrustInterface


def test_memory_integration_reexports_canonical_symbols():
    """Legacy ``memory.integration`` imports should use canonical src modules."""
    assert MemoryClient.__module__ == "src.integration.memory_client"
    assert ContextLoader.__module__ == "src.integration.context_loader"
    assert MCPOperation.GET_CONTEXT.value == "getContext"


def test_memory_integration_submodules_reexport_canonical_symbols():
    """Legacy direct submodule imports should not use stale duplicate code."""
    assert SubmoduleMemoryClient.__module__ == "src.integration.memory_client"
    assert SubmoduleContextLoader.__module__ == "src.integration.context_loader"
    assert SubmoduleTrustInterface.__module__ == "src.integration.trust_interface"
