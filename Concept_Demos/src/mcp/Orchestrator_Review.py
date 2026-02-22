Defined but no initialized
def _get_run_logger():
    """Lazy load run logger to avoid circular imports."""
    global _run_logger
    if _run_logger is None:
        try:
            from ..utils.run_logger import get_run_logger

            _run_logger = get_run_logger()
        except Exception:
            _run_logger = None
    return _run_logger

class Orchestrator:
        def __init__(self) -> None:
            # Obsidian integration components
        self.obs_manager = ObsidianManager(OBSIDIAN_VAULT_PATH)
        self.obs_parser = ObsidianParser()
        self.obs_generator = ObsidianGenerator()

        # Initialize Hebbian learning layer
        self.hebbian = HebbianWeightManager()

        # Initialize hybrid memory layer (vector + explicit Obsidian)
        self.vector_store = LocalVectorStore()
        self.governance_monitor = GovernanceMonitor()
        self.memory_bus = MemoryBus(
            self.obs_manager,
            self.vector_store,
            search_dirs=[AGENT_INPUT_DIR, AGENT_OUTPUT_DIR],
            governance_monitor=self.governance_monitor,)

class
        # Initialize Agent Registry
        self.agent_registry = AgentRegistry()
        self._register_agents()

        self._ensure_obsidian_agent_dirs()
        self._validate_kernel_state()
        logger.info("MCP Orchestrator initialized with Agent Registry.")


        Explore: Frontend API Integration. API client functions for agent and task management
Start from: api.ts, index.ts w
