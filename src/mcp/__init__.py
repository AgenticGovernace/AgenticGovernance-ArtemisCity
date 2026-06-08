"""MCP layer exports: orchestrator, config, and memory-learning utilities."""

from .config import AGENT_INPUT_DIR, AGENT_OUTPUT_DIR, OBSIDIAN_VAULT_PATH
from .hebbian_weights import HebbianWeightManager
from .orchestrator import Orchestrator
from .vector_store import LocalVectorStore, VectorRecord

__all__ = [
    "Orchestrator",
    "HebbianWeightManager",
    "LocalVectorStore",
    "VectorRecord",
    "OBSIDIAN_VAULT_PATH",
    "AGENT_INPUT_DIR",
    "AGENT_OUTPUT_DIR",
]
