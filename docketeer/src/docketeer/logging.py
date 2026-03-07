"""Centralized logging configuration for Docketeer."""

import logging
import logging.config
from pathlib import Path
from typing import Final

from docketeer.environment import get_log_level

# Packages that should have their minimum logging level set to INFO
# These packages have extremely verbose DEBUG logging that's not useful for normal operation
_VERBOSE_PACKAGES: Final[set[str]] = {
    "docket",  # pydocket scheduling library
    "httpx",  # HTTP client
    "websockets",  # WebSocket client/server
    "httpcore",  # HTTP core library (includes http11, connection, etc.)
    "mcp.server.lowlevel",  # MCP low-level server dispatch
    "markdown_it",  # Markdown parser
    "openai",  # OpenAI API client library
}

_LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(*, log_file: Path | None = None) -> Path | None:
    """Configure logging based on DOCKETEER_LOG_LEVEL environment variable.

    Sets the global logging level from DOCKETEER_LOG_LEVEL (default: INFO).
    Forces verbose packages to log at INFO minimum level.

    When log_file is provided, logs go to that file instead of stderr.
    Returns the log file path if file logging was set up.
    """
    # Get the configured log level, defaulting to INFO
    try:
        level = get_log_level("LOG_LEVEL", logging.INFO)
    except ValueError:
        # Use basic logging to report the error since we haven't configured logging yet
        logging.basicConfig(level=logging.ERROR)
        log = logging.getLogger(__name__)
        log.exception("Failed to configure logging")
        raise

    root = logging.getLogger()
    root.setLevel(level)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)

    # Set minimum level for verbose packages
    for package in _VERBOSE_PACKAGES:
        logger = logging.getLogger(package)
        logger.setLevel(max(level, logging.INFO))

    log = logging.getLogger(__name__)
    log.debug("Logging configured at level %s", logging.getLevelName(level))
    return log_file
