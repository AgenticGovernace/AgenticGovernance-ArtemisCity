import logging
import os
from logging import Logger


def setup_logging():
    """Configure the standard Python logger for MCP system.
    
    Returns:
        None: This function does not return a value.
    """
    log_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "../../Concept_Demos/src", "..", "mcp_obsidian.log"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )
    return logging.getLogger("MCP_System")


logger: Logger = setup_logging()

# Re-export run_logger utilities for convenience

__all__ = ["logger", "setup_logging", "RunLogger", "get_run_logger", "init_run_logger"]
