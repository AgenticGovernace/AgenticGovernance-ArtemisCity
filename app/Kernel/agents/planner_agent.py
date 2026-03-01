"""PlannerAgent Module for Task Planning in Artemis City.

This module provides the PlannerAgent, a specialized agent responsible
for breaking down complex requests into actionable, structured plans.
It generates task plans with discrete steps and stores them in the
memory system for execution tracking and reference.

The PlannerAgent is designed to handle requests that require multi-step
execution strategies, providing a systematic approach to complex tasks.

Typical usage example:
    planner = PlannerAgent("planner")
    memory = MemoryBus()
    plan = planner.handle({"content": "refactor authentication module"}, memory)
    print(plan)

Version: 1.0.0
License: MIT
"""

from .base import Agent


class PlannerAgent(Agent):
    """Specialized agent for generating structured task plans.

    The PlannerAgent analyzes incoming requests and generates
    structured plans with discrete steps following a standard
    Analyze-Execute-Verify pattern. Plans are stored in memory
    for execution tracking, auditability, and future reference.

    Attributes:
        name (str): The identifier name for this agent instance.

    Inherits from:
        Agent: Abstract base class defining the agent interface.

    Example:
        >>> planner = PlannerAgent("planner")
        >>> memory = MemoryBus()
        >>> plan = planner.handle({"content": "refactor module"}, memory)
        >>> print(plan)
        Plan for 'refactor module':
        1. Analyze
        2. Execute
        3. Verify
    """

    def handle(self, request, memory):
        """Generate a structured plan for the requested task.

        Creates a simple three-step plan (Analyze, Execute, Verify)
        for the given request and stores it in memory. This standardized
        approach ensures consistent planning across different task types.

        Args:
            request (dict): Dictionary containing the request. Expected keys:
                - content (str): Description of the task to plan.
            memory (MemoryBus): MemoryBus instance for storing the generated plan.

        Returns:
            str: A formatted plan string with numbered steps in the format:
                "Plan for '<task>':\n1. Analyze\n2. Execute\n3. Verify"

        Side Effects:
            - Writes plan to memory bus with metadata
            - Metadata includes source agent and plan type

        Example:
            >>> planner = PlannerAgent("planner")
            >>> memory = MemoryBus()
            >>> plan = planner.handle({"content": "deploy service"}, memory)
            >>> print(plan)
            Plan for 'deploy service':
            1. Analyze
            2. Execute
            3. Verify
        """
        content = request.get("content", "")
        plan = f"Plan for '{content}':\n1. Analyze\n2. Execute\n3. Verify"

        memory.write(plan, metadata={"source": "PlannerAgent", "type": "plan"})

        return plan
