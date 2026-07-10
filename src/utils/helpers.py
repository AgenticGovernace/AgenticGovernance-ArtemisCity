import logging
import os
from logging import Logger


def setup_logging():
    """Configure the standard Python logger for MCP system.

    Writes to ``$ARTEMIS_LOG_FILE`` when set, otherwise falls back to
    ``logs/mcp_obsidian.log`` at the repo root. Crucially, a missing or
    unwritable log path no longer crashes the import — we degrade to
    stream-only logging instead. Importing this module is a side-effect
    of every bridge / orchestrator import, so an import-time crash here
    takes the whole subprocess down.

    Returns:
        logging.Logger: The configured ``MCP_System`` logger.
    """
    default_log = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "../..",
        "logs",
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


def sanitize_for_log(value: object, max_length: int = 200) -> str:
    """Sanitize an untrusted value before it is written to a log line.

    Task titles, agent names, note paths, and similar values originate in
    user-editable Obsidian notes / HTTP payloads, so they must not be able
    to forge log records.

    The pattern is deliberate: a ``.replace`` chain on the newline / CR /
    tab characters followed by a printable-only whitelist. CodeQL's
    ``py/log-injection`` query recognizes the ``.replace`` chain as a
    log-newline-injection sanitizer, which is what flags this helper as
    a recognized sink protector across the codebase. The whitelist
    catches anything else non-printable (zero-width chars, control
    chars, etc.) without depending on CodeQL recognising
    ``str.isprintable``. Finally the result is truncated to
    ``max_length`` characters so a hostile value cannot flood the log.

    Args:
        value: Any value; coerced with ``str()`` first.
        max_length: Maximum number of characters to keep (default 200).

    Returns:
        str: The sanitized, truncated representation safe for logging.
    """
    text = (
        str(value)
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
    )
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    if len(text) > max_length:
        text = text[:max_length] + "…"
    return text


# Re-export run_logger utilities for convenience

__all__ = [
    "logger",
    "sanitize_for_log",
    "setup_logging",
    "RunLogger",
    "get_run_logger",
    "init_run_logger",
]
