"""Default daemon agent for the Artemis City kernel.

The daemon agent is the system anchor and memory interface. It handles
general system, status, and memory commands and also serves as the
fallback handler when the router does not match a more specialized agent.
"""

from .base import Agent


class DaemonAgent(Agent):
    """System-anchor agent and default command handler.

    Acknowledges incoming commands and records them to the memory bus
    when one is available. Concrete behaviour is intentionally minimal at
    this stage; the daemon exists to give the kernel a working default
    route while richer capabilities are layered on in later phases.
    """

    def handle(self, request, memory):
        """Acknowledge a command and persist it to memory.

        Args:
            request: Request dictionary; the ``content`` key holds the
                command text.
            memory: Optional :class:`~app.kernel.memory_bus.MemoryBus`
                used to record the interaction.

        Returns:
            str: A short acknowledgement of the handled command.
        """
        content = request.get("content", "")
        if memory is not None:
            memory.write(content, metadata={"source": self.name, "type": "command"})
        return f"[{self.name}] Acknowledged: {content}"
