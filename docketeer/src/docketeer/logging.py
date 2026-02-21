"""Centralized logging configuration for Docketeer."""

import logging
import logging.config
from typing import Final

from docketeer.environment import get_log_level

# Packages that should have their minimum logging level set to INFO
# These packages have extremely verbose DEBUG logging that's not useful for normal operation
_VERBOSE_PACKAGES: Final[set[str]] = {
    "docket",  # pydocket scheduling library
    "httpx",  # HTTP client
    "websockets",  # WebSocket client/server
    "httpcore",  # HTTP core library (includes http11, connection, etc.)
    "openai",  # OpenAI API client library
}


def configure_logging() -> None:
    """Configure logging based on DOCKETEER_LOG_LEVEL environment variable.

    Sets the global logging level from DOCKETEER_LOG_LEVEL (default: INFO).
    Forces verbose packages to log at INFO minimum level.
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

    # Configure the root logger with our standard format
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Set minimum level for verbose packages
    for package in _VERBOSE_PACKAGES:
        logger = logging.getLogger(package)
        logger.setLevel(max(level, logging.INFO))

    log = logging.getLogger(__name__)
    log.debug("Logging configured at level %s", logging.getLevelName(level))
