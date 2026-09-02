"""Planner agent for the Artemis City kernel.

The planner agent drafts lightweight execution plans for planning-oriented
commands (roadmaps, blueprints, schedules).
"""

from .base import Agent


class PlannerAgent(Agent):
    """Agent that drafts execution plans for planning commands.

    Produces a placeholder plan for the supplied command and records the
    request to the memory bus when one is available. The planning logic is
    intentionally minimal at this stage and will be expanded in later phases.
    """

    def handle(self, request, memory):
        """Draft a plan for a command and persist it to memory.

        Args:
            request: Request dictionary; the ``content`` key holds the
                command text.
            memory: Optional :class:`~app.kernel.memory_bus.MemoryBus`
                used to record the interaction.

        Returns:
            str: A short summary describing the drafted plan.
        """
        content = request.get("content", "")
        if memory is not None:
            memory.write(content, metadata={"source": self.name, "type": "plan"})
        return f"[{self.name}] Draft plan for: {content}"
