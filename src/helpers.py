import logging
import os


def setup_logging():
    """Configure the standard Python logger for MCP system."""
    log_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "mcp_obsidian.log"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )
    return logging.getLogger("MCP_System")


logger = setup_logging()

# Re-export run_logger utilities for convenience
from .run_logger import RunLogger, get_run_logger, init_run_logger

__all__ = ["logger", "setup_logging", "RunLogger", "get_run_logger", "init_run_logger"]
