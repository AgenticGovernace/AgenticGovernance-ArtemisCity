"""ArtemisCliAgent Module for Artemis City System.

This module provides the ArtemisCliAgent, the default general-purpose agent
that handles requests not specifically routed to other specialized agents.
It simulates LLM-based processing and logs all interactions to the memory
bus for auditability and future reference.

The ArtemisCliAgent serves as a fallback handler ensuring that all commands
receive a response, even when they don't match specific agent keywords.

Typical usage example:
    agent = ArtemisCliAgent("artemis-cli")
    response = agent.handle({"content": "status"}, memory_bus)
    print(response)

Version: 1.0.0
License: MIT
"""

from .base import Agent


class ArtemisCliAgent(Agent):
    """General-purpose agent for processing commands in Artemis City.

    The ArtemisCliAgent serves as the default handler for commands that
    are not specifically routed to other specialized agents. It processes
    requests, simulates LLM responses, and stores interactions in the
    memory bus for future reference and auditability.

    Attributes:
        name (str): The identifier name for this agent instance.

    Inherits from:
        Agent: Abstract base class defining the agent interface.

    Example:
        >>> agent = ArtemisCliAgent("artemis-cli")
        >>> memory = MemoryBus()
        >>> response = agent.handle({"content": "status"}, memory)
        >>> print(response)
        I am ArtemisCliAgent. I processed your request: 'status'. (LLM Simulation)
    """

    def handle(self, request, memory):
        """Process a request and return a simulated LLM response.

        Extracts the content from the request, generates a simulated
        response, and stores the interaction in memory for audit
        and retrieval purposes.

        Args:
            request (dict): Dictionary containing the request. Expected keys:
                - content (str): The command or message to process.
            memory (MemoryBus): MemoryBus instance for storing the interaction.

        Returns:
            str: A formatted response indicating the request was processed,
                including the agent name and original request content.

        Side Effects:
            - Writes interaction to memory bus with metadata
            - Metadata includes source agent and triggering content

        Example:
            >>> agent = ArtemisCliAgent("daemon")
            >>> memory = MemoryBus()
            >>> response = agent.handle({"content": "check health"}, memory)
            >>> print(response)
            I am ArtemisCliAgent. I processed your request: 'check health'...
        """
        content = request.get("content", "")

        # Simulate LLM call
        response = f"I am ArtemisCliAgent. I processed your request: '{content}'. (LLM Simulation)"

        # Write to memory
        memory.write(response, metadata={"source": "ArtemisCliAgent", "trigger": content})

        return response
