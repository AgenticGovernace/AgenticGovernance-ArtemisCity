"""Artemis City Core Kernel Module.

This module implements the central kernel for the Artemis City agentic governance
system, responsible for orchestrating command processing, agent routing, and
memory management. The Kernel acts as the primary coordinator for all agent
interactions within the system.

The Kernel maintains persistent state across sessions, provides the main entry
point for processing user requests through its agent network, and ensures proper
initialization and coordination of all subsystems including the AgentRouter and
MemoryBus.

Typical usage example:
    kernel = Kernel()
    result = kernel.process({"type": "command", "content": "status"})
    print(result)

Dependencies:
    - json: State serialization and deserialization
    - os: File system operations for state persistence

Constants:
    STATE_FILE (str): Path to the kernel state persistence file.

Version: 1.0.0
License: MIT
"""

import json
import os

from .agent_router import AgentRouter
from .agents.artemis_cli_agent import ArtemisCliAgent
from .agents.planner_agent import PlannerAgent
from .memory_bus import MemoryBus

STATE_FILE = "state_kernel.json"


class Kernel:
    """Artemis City Core Kernel for orchestrating agent operations.

    The Kernel is the central coordinator of the Artemis City system,
    managing command routing, agent instantiation, and persistent state.
    It initializes and coordinates all subsystems including the AgentRouter
    for command routing, MemoryBus for persistent memory operations, and
    individual agent instances.

    Attributes:
        booted: Boolean indicating whether the kernel has completed initialization.
        state: Dictionary containing kernel state including command history
            and boot count.
        router: AgentRouter instance for routing commands to appropriate agents.
        memory: MemoryBus instance for persistent memory operations.

    Example:
        >>> kernel = Kernel()
        >>> result = kernel.process({"type": "command", "content": "status"})
        >>> print(result)
    """

    def __init__(self):
        """Initialize the Kernel and boot all subsystems.

        Creates a new Kernel instance and immediately boots all subsystems
        including the agent router and memory bus. State is loaded from
        disk if available, or initialized with defaults.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            - Loads or creates kernel state file
            - Initializes AgentRouter and MemoryBus
            - Increments boot count in persistent state
        """
        self.booted = False
        self.state = {}
        self.router = None
        self.memory = None
        self.boot()

    def boot(self):
        """Initialize kernel subsystems: Router, Memory, and Agents.

        Loads persistent state from disk, initializes the AgentRouter
        for command routing, and creates the MemoryBus for memory
        operations. Sets the booted flag to True upon completion.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            - Loads state from STATE_FILE
            - Creates AgentRouter instance
            - Creates MemoryBus instance
            - Sets self.booted to True
        """
        self._load_state()
        self.router = AgentRouter()
        self.memory = MemoryBus()
        self.booted = True

    def _load_state(self):
        """Load the kernel state from disk.

        Attempts to load previously saved kernel state from STATE_FILE.
        If the file doesn't exist or fails to load, initializes with
        default state containing empty history and zero boot count.
        Increments boot_count and saves state on each load.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            - Reads from STATE_FILE if it exists
            - Sets self.state with loaded or default data
            - Increments boot_count
            - Calls _save_state() to persist updated state
            - Prints error message if state loading fails
        """
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    self.state = json.load(f)
            except Exception as e:
                print(f"[Kernel] Failed to load state: {e}")
                self.state = {"history": [], "boot_count": 0}
        else:
            self.state = {"history": [], "boot_count": 0}

        self.state["boot_count"] = self.state.get("boot_count", 0) + 1
        self._save_state()

    def _save_state(self):
        """Save the kernel state to disk.

        Persists the current kernel state to STATE_FILE in JSON format.
        Logs an error message if the save operation fails.

        Args:
            None.

        Returns:
            None.

        Side Effects:
            - Writes to STATE_FILE with indented JSON
            - Prints error message if save operation fails
        """
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"[Kernel] Failed to save state: {e}")

    def process(self, request):
        """Main execution entry point for processing requests.

        Routes incoming requests to appropriate handlers based on request
        type. Logs all requests to the state history for auditability.
        Supports both command processing and plan execution.

        Args:
            request (dict): A dictionary containing the request details.
                Expected keys:
                    - type (str): Request type ('command' or 'exec')
                    - content (str): Command content (for 'command' type)
                    - path (str): Plan file path (for 'exec' type)

        Returns:
            str: The result message from processing the request,
                including the agent response or error message.

        Side Effects:
            - Appends request to state history
            - Saves state to disk
            - Invokes agent handlers that may have their own side effects

        Example:
            >>> kernel = Kernel()
            >>> result = kernel.process({"type": "command", "content": "status"})
            >>> print(result)
            [Agent_Name] Processing command...
        """
        content = request.get("content", "")
        request_type = request.get("type", "command")

        # Log to history
        if "history" not in self.state:
            self.state["history"] = []
        self.state["history"].append(request)
        self._save_state()

        if request_type == "command":
            return self._handle_command(content)
        elif request_type == "exec":
            return f"[Kernel] Executing plan: {request.get('path')}"

        return f"[Kernel] Unknown request type: {request_type}"

    def _get_agent_instance(self, agent_name):
        """Create and return an agent instance based on agent name.

        Factory method that instantiates the appropriate agent class
        based on the provided agent name. Falls back to a generic
        ArtemisCliAgent if the agent name is not recognized.

        Args:
            agent_name (str): Name of the agent to instantiate. Supported values:
                - 'planner': Returns PlannerAgent
                - 'daemon': Returns ArtemisCliAgent
                - 'artemis-cli': Returns ArtemisCliAgent
                - Other: Returns generic ArtemisCliAgent

        Returns:
            Agent: An instance of the appropriate Agent subclass
                (PlannerAgent or ArtemisCliAgent).

        Example:
            >>> agent = kernel._get_agent_instance("planner")
            >>> type(agent).__name__
            'PlannerAgent'
        """
        if agent_name == "planner":
            return PlannerAgent(agent_name)
        elif agent_name == "daemon" or agent_name == "artemis-cli":
            return ArtemisCliAgent(agent_name)
        return ArtemisCliAgent("generic")

    def _handle_command(self, command):
        """Handle a command by routing to the appropriate agent.

        Uses the AgentRouter to determine which agent should handle
        the command, instantiates the agent, and delegates execution.

        Args:
            command (str): The command string to process.

        Returns:
            str: The formatted response from the handling agent,
                or an error message if the router is not initialized.

        Example:
            >>> result = kernel._handle_command("status")
            >>> print(result)
            [Agent] Simulated response for 'status'...
        """
        if not self.router:
            return "[Kernel] Router not initialized."

        route = self.router.route(command)
        agent_name = route.get("agent")
        # metadata = route.get("metadata", {})

        agent = self._get_agent_instance(agent_name)

        request = {"content": command, "type": "command"}
        result = agent.handle(request, self.memory)

        return f"[Kernel] {agent_name} responded:\n{result}"
