"""Memory bus system for persistent agent memory operations.

This module provides a pluggable memory backend system for the Artemis
City framework. It implements multiple storage backends for persisting
agent interactions and enables memory queries across stored content.

Supported backends:
- file: Local JSON file storage (default, development)
- vector: Supabase pgvector for semantic search (production)
- mcp: Obsidian MCP server via MemoryClient

The MemoryBus acts as an abstraction layer over different storage backends,
allowing agents to store and retrieve information without coupling to
specific storage implementations.
"""

import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from src.runtime_paths import data_path


class MemoryBackend(ABC):
    """Abstract base class for memory storage backends.

    Defines the interface that all memory backends must implement,
    ensuring consistent read/write operations across different
    storage implementations.
    """

    @abstractmethod
    def write(self, content, metadata=None):
        """Write content to the memory backend.

        Args:
            content: The content to store.
            metadata: Optional metadata dictionary to associate with
                the content.

        Returns:
            Implementation-specific identifier or path for the stored
            content, or None if the operation failed.
        """
        raise NotImplementedError

    @abstractmethod
    def read(self, query, limit: int = 10):
        """Read content from the memory backend matching a query.

        Args:
            query: Search query string to match against stored content.
            limit: Maximum number of results (backends may ignore this).

        Returns:
            List of matching content entries.
        """
        raise NotImplementedError


class FileMemoryBackend(MemoryBackend):
    """File-based memory storage backend.

    Stores memory entries as individual JSON files in a specified
    directory. Each entry includes content, metadata, and timestamps.
    Supports basic search by matching query strings against content.

    Attributes:
        base_path: Directory path where memory files are stored.
    """

    def __init__(self, base_path: Optional[str] = None):
        """Initialize the file-based memory backend.

        Args:
            base_path: Directory path for storing memory files.
                Created if it doesn't exist.
        """
        self.base_path = data_path(
            "memory_store",
            base_path,
            env_var="ARTEMIS_MEMORY_STORE_DIR",
        )
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

    def write(self, content, metadata=None):
        """Write content to a JSON file in the memory store.

        Creates a timestamped JSON file containing the content,
        metadata, and write timestamp.

        Args:
            content: The content to store.
            metadata: Optional dictionary of metadata. If it includes
                a 'source' key, that value is used in the filename.

        Returns:
            str: Path to the created file if successful, None otherwise.
        """
        metadata = metadata or {}
        # Append a uuid suffix so two writes from the same source within a
        # single second don't collide on the second-resolution timestamp.
        suffix = uuid.uuid4().hex[:8]
        source = metadata.get("source", "unknown")
        filename = f"{int(time.time())}_{source}_{suffix}.json"
        filepath = os.path.join(self.base_path, filename)
        data = {"content": content, "metadata": metadata, "timestamp": time.time()}
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return filepath
        except Exception as e:
            print(f"[Memory] Write failed: {e}")
            return None

    def read(self, query, limit: int = 10):
        """Search stored memories for content matching a query.

        Performs a case-insensitive substring search across all
        stored memory files, returning entries where the content
        contains the query string.

        Args:
            query: Search string to match against stored content.

        Returns:
            list: List of matching memory entries (dictionaries with
                'content', 'metadata', and 'timestamp' keys).
        """
        results = []
        if limit <= 0 or not os.path.exists(self.base_path):
            return results

        for f in sorted(os.listdir(self.base_path), reverse=True):
            if f.endswith(".json"):
                try:
                    with open(
                        os.path.join(self.base_path, f), "r", encoding="utf-8"
                    ) as file:
                        data = json.load(file)
                        if query.lower() in str(data.get("content", "")).lower():
                            results.append(data)
                            if len(results) >= limit:
                                break
                except Exception:
                    continue
        return results


class VectorMemoryBackend(MemoryBackend):
    """Adapter over the canonical local vector store for semantic search.

    Provides semantic search capabilities using embeddings and
    vector similarity while preserving the kernel memory-backend contract.

    Attributes:
        vector_store: VectorStore instance for operations
    """

    def __init__(self):
        """Initialize vector memory backend."""
        try:
            from src.mcp.vector_store import LocalVectorStore

            self.vector_store = LocalVectorStore()
            self._available = True
        except Exception as e:
            print(f"[Memory] VectorStore not available: {e}")
            self._available = False
            self.vector_store = None

    def write(self, content: str, metadata: Optional[Dict] = None) -> Optional[str]:
        """Write content to vector store.

        Args:
            content: Content to store
            metadata: Optional metadata

        Returns:
            Document ID if successful, None otherwise
        """
        if not self._available or self.vector_store is None:
            print("[Memory] Vector backend not available")
            return None

        try:
            record_metadata = dict(metadata or {})
            doc_id = str(record_metadata.pop("doc_id", uuid.uuid4().hex))
            self.vector_store.upsert(doc_id, content, record_metadata)
            return doc_id
        except Exception as e:
            print(f"[Memory] Vector write failed: {e}")
            return None

    def read(self, query: str, limit: int = 10) -> List[Dict]:
        """Semantic search for content.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching entries
        """
        if not self._available or self.vector_store is None:
            return []

        try:
            results = self.vector_store.query(query, top_k=limit, include_content=True)
            return [
                {
                    "content": content,
                    "metadata": metadata,
                    "timestamp": metadata.get(
                        "stored_at", metadata.get("last_access", 0)
                    ),
                    "similarity": similarity,
                }
                for _doc_id, similarity, metadata, content in results
            ]
        except Exception as e:
            print(f"[Memory] Vector search failed: {e}")
            return []


class MemoryBus:
    """High-level memory interface for agent memory operations.

    Provides an abstraction layer over memory backends, allowing
    agents to perform memory operations without coupling to specific
    storage implementations.

    Supported backends:
    - 'file': Local JSON file storage (default)
    - 'vector': Supabase pgvector semantic search
    - Custom backend instance can be passed directly

    Attributes:
        backend: The underlying MemoryBackend implementation.
        backend_type: String identifier for the backend type.
    """

    def __init__(
        self,
        backend_type: str = "file",
        backend: Optional[MemoryBackend] = None,
        file_base_path: Optional[str] = None,
    ):
        """Initialize the MemoryBus with the specified backend.

        Args:
            backend_type: Type of backend to use:
                - 'file': File-based storage (default)
                - 'vector': Supabase pgvector semantic search
            backend: Optional custom backend instance (overrides backend_type)
        """
        self.backend_type = backend_type

        if backend is not None:
            self.backend = backend
        elif backend_type == "file":
            self.backend = FileMemoryBackend(file_base_path)
        elif backend_type == "vector":
            self.backend = VectorMemoryBackend()
        else:
            print(f"[Memory] Unknown backend {backend_type}, defaulting to file.")
            self.backend = FileMemoryBackend(file_base_path)
            self.backend_type = "file"

    def write(self, content: str, metadata: Optional[Dict] = None) -> Optional[str]:
        """Write content to the memory backend.

        Args:
            content: The content to store.
            metadata: Optional metadata dictionary.

        Returns:
            Implementation-specific result from the backend write operation.
        """
        return self.backend.write(content, metadata)

    def read(self, query: str, limit: int = 10) -> List[Dict]:
        """Query the memory backend for matching content.

        Args:
            query: Search query string.
            limit: Maximum number of results (for backends that support it).

        Returns:
            List of matching memory entries from the backend.
        """
        return self.backend.read(query, limit=limit)

    def is_semantic(self) -> bool:
        """Check if backend supports semantic search.

        Returns:
            True if using vector backend with semantic capabilities.
        """
        return self.backend_type == "vector" and bool(
            getattr(self.backend, "_available", True)
        )
