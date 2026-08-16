"""
Type definitions for the Artemis-City MCP framework.

This module provides TypedDict definitions and type aliases that enforce
type safety across the codebase, following JSF AV Rules 209 and 147.

Module Dependencies:
    - typing (standard library)
    - typing_extensions (for NotRequired on Python < 3.11)

Author: Artemis-City Contributors
Date: 2024
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

# Use typing_extensions for Python 3.8-3.10 compatibility
try:
    from typing import NotRequired, TypedDict
except ImportError:
    from typing_extensions import NotRequired, TypedDict


# =============================================================================
# Task-Related Types
# =============================================================================


class TaskContext(TypedDict, total=False):
    """
    Context dictionary passed to agents for task execution.

    Required Fields:
        task_id: Unique identifier for the task.
        title: Human-readable task title.
        required_capability: The capability needed to execute this task.

    Optional Fields:
        content: Main content/body of the task.
        context: Additional contextual information.
        agent: Preferred agent name (if specified).
        atp_mode: Artemis Transmission Protocol mode.
        query: Search or lookup query string.
        request_feedback: Whether to request feedback after completion.
        memory_context: Enriched context from memory bus retrieval.
        status: Current task status.

    Example:
        >>> task: TaskContext = {
        ...     "task_id": "task_001",
        ...     "title": "Analyze codebase",
        ...     "required_capability": "system_management",
        ...     "content": "Review the MCP module structure",
        ... }
    """

    task_id: str
    title: str
    required_capability: str
    content: NotRequired[str]
    context: NotRequired[str]
    agent: NotRequired[str]
    atp_mode: NotRequired[str]
    query: NotRequired[str]
    request_feedback: NotRequired[bool]
    memory_context: NotRequired[List[Dict[str, Any]]]
    status: NotRequired[str]


class TaskResult(TypedDict, total=False):
    """
    Result dictionary returned by agents after task execution.

    Required Fields:
        status: Execution status ("success" or "failed").
        summary: Human-readable summary of the result.

    Optional Fields:
        error: Error message if status is "failed".
        narrative: Extended narrative output.
        semantic_tags: List of semantic tags extracted.
        concepts: List of concepts identified.
        persona_context: Persona-specific context data.
        recent_context: Recent context window data.
        data: Additional structured data.

    Example:
        >>> result: TaskResult = {
        ...     "status": "success",
        ...     "summary": "Analysis completed successfully",
        ...     "concepts": ["architecture", "modularity"],
        ... }
    """

    status: Literal["success", "failed"]
    summary: str
    error: NotRequired[str]
    narrative: NotRequired[str]
    semantic_tags: NotRequired[List[str]]
    concepts: NotRequired[List[str]]
    persona_context: NotRequired[Dict[str, Any]]
    recent_context: NotRequired[List[str]]
    data: NotRequired[Dict[str, Any]]


class ExecutionSummary(TypedDict):
    """
    Summary of batch task execution results.

    Fields:
        total: Total number of tasks processed.
        completed: Number of successfully completed tasks.
        failed: Number of failed tasks.
        skipped: Number of skipped tasks.
        details: Per-task result details.
    """

    total: int
    completed: int
    failed: int
    skipped: int
    details: List[Dict[str, Any]]


# =============================================================================
# Agent-Related Types
# =============================================================================


class AgentCapability(TypedDict):
    """
    Definition of an agent capability.

    Fields:
        name: Capability identifier.
        description: Human-readable description.
        priority: Priority weight for routing (higher = preferred).
    """

    name: str
    description: str
    priority: int


class AgentConfig(TypedDict, total=False):
    """
    Configuration for agent router entries.

    Required Fields:
        role: The role/purpose of the agent.
        keywords: List of routing keywords.

    Optional Fields:
        action_description: Description of expected actions.
        capabilities: List of capability names.
    """

    role: str
    keywords: List[str]
    action_description: NotRequired[str]
    capabilities: NotRequired[List[str]]


class AgentRouterConfig(TypedDict):
    """
    Root configuration for the agent router.

    Fields:
        agents: Mapping of agent names to their configurations.
    """

    agents: Dict[str, AgentConfig]


# =============================================================================
# Memory and Governance Types
# =============================================================================


class MemoryEntry(TypedDict, total=False):
    """
    An entry in the memory system.

    Required Fields:
        content: The text content of the memory.
        source: Origin of the memory (file path, agent name, etc.).

    Optional Fields:
        embedding: Vector embedding of the content.
        metadata: Additional metadata.
        timestamp: When the memory was created/updated.
        score: Relevance score from retrieval.
    """

    content: str
    source: str
    embedding: NotRequired[List[float]]
    metadata: NotRequired[Dict[str, Any]]
    timestamp: NotRequired[float]
    score: NotRequired[float]


class GovernanceEvent(TypedDict, total=False):
    """
    A governance monitoring event.

    Required Fields:
        type: Event type identifier.
        timestamp: Unix timestamp of the event.

    Optional Fields:
        message: Human-readable message.
        failures_in_streak: Count of consecutive failures.
        details: Additional event details.
    """

    type: str
    timestamp: float
    message: NotRequired[str]
    failures_in_streak: NotRequired[int]
    details: NotRequired[Dict[str, Any]]


# =============================================================================
# Hebbian Learning Types
# =============================================================================


class HebbianConnection(TypedDict):
    """
    A connection in the Hebbian learning network.

    Fields:
        source: Source node identifier.
        target: Target node identifier.
        weight: Connection weight (0.0 to 100.0).
        activations: Total activation count.
        successes: Successful activation count.
    """

    source: str
    target: str
    weight: float
    activations: int
    successes: int


class HebbianNetworkSummary(TypedDict):
    """
    Summary statistics for the Hebbian network.

    Fields:
        total_connections: Number of connections in the network.
        average_weight: Mean weight across all connections.
        max_weight: Maximum weight in the network.
        total_activations: Sum of all activations.
        success_rate: Overall success rate (0.0 to 1.0).
    """

    total_connections: int
    average_weight: float
    max_weight: float
    total_activations: int
    success_rate: float


# =============================================================================
# Type Aliases
# =============================================================================

# Generic JSON-compatible type
JSONValue = Union[str, int, float, bool, None, Dict[str, Any], List[Any]]
JSONDict = Dict[str, JSONValue]

# Path types
NotePath = str  # Relative path within Obsidian vault
FilePath = str  # Absolute or relative filesystem path

# Capability identifier
CapabilityName = str

# Agent identifier
AgentName = str
