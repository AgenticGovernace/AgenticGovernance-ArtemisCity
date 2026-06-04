import logging
import os
from logging import Logger


def setup_logging():
    """Configure the standard Python logger for MCP system.

    Writes to ``$ARTEMIS_LOG_FILE`` when set, otherwise falls back to the
    historical Concept_Demos path for local dev. Crucially, a missing or
    unwritable log path no longer crashes the import — we degrade to
    stream-only logging instead. Importing this module is a side-effect
    of every bridge / orchestrator import, so an import-time crash here
    takes the whole subprocess down.

    Returns:
        logging.Logger: The configured ``MCP_System`` logger.
    """
    default_log = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "../../Concept_Demos/src",
        "..",
        "mcp_obsidian.log",
    )
    log_file = os.environ.get("ARTEMIS_LOG_FILE", default_log)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        handlers.insert(0, logging.FileHandler(log_file))
    except (OSError, PermissionError):
        # File logging unavailable (read-only FS, missing parent dir we
        # can't create, etc.). Stream-only is enough; do not crash.
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )
    return logging.getLogger("MCP_System")


logger: Logger = setup_logging()

# Re-export run_logger utilities for convenience

__all__ = ["logger", "setup_logging", "RunLogger", "get_run_logger", "init_run_logger"]
