"""Tests for docketeer.logging module."""

import logging
from collections.abc import Generator
from pathlib import Path

import pytest

from docketeer.logging import configure_logging


@pytest.fixture(autouse=True)
def _isolate_logging() -> Generator[None]:
    """Save and restore root logger state around each test."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    for handler in root.handlers[:]:
        if handler not in original_handlers:
            handler.close()
            root.removeHandler(handler)
    root.handlers = original_handlers
    root.setLevel(original_level)


def test_configure_logging_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test logging configuration with default (INFO) level."""
    # Clear any existing logging configuration
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)

    # Ensure no environment variable is set
    monkeypatch.delenv("DOCKETEER_LOG_LEVEL", raising=False)

    configure_logging()

    # Check that root logger is configured
    assert logging.root.level == logging.INFO

    # Check that verbose packages are clamped to INFO
    verbose_packages = [
        "docket",
        "httpx",
        "websockets",
        "httpcore",
        "markdown_it",
        "mcp.server.lowlevel",
        "openai",
    ]
    for package in verbose_packages:
        logger = logging.getLogger(package)
        assert logger.level == logging.INFO


def test_configure_logging_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test logging configuration with DEBUG level."""
    # Clear any existing logging configuration
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)

    monkeypatch.setenv("DOCKETEER_LOG_LEVEL", "DEBUG")

    configure_logging()

    # Check that root logger is configured to DEBUG
    assert logging.root.level == logging.DEBUG

    # Check that verbose packages are clamped to INFO (not DEBUG)
    verbose_packages = [
        "docket",
        "httpx",
        "websockets",
        "httpcore",
        "markdown_it",
        "mcp.server.lowlevel",
        "openai",
    ]
    for package in verbose_packages:
        logger = logging.getLogger(package)
        assert logger.level == logging.INFO


def test_configure_logging_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test logging configuration with WARNING level."""
    # Clear any existing logging configuration
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)

    monkeypatch.setenv("DOCKETEER_LOG_LEVEL", "WARNING")

    configure_logging()

    # Check that root logger is configured to WARNING
    assert logging.root.level == logging.WARNING

    # Check that verbose packages are at WARNING (not clamped)
    verbose_packages = [
        "docket",
        "httpx",
        "websockets",
        "httpcore",
        "markdown_it",
        "mcp.server.lowlevel",
        "openai",
    ]
    for package in verbose_packages:
        logger = logging.getLogger(package)
        assert logger.level == logging.WARNING


def test_configure_logging_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test logging configuration with ERROR level."""
    # Clear any existing logging configuration
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)

    monkeypatch.setenv("DOCKETEER_LOG_LEVEL", "ERROR")

    configure_logging()

    # Check that root logger is configured to ERROR
    assert logging.root.level == logging.ERROR

    # Check that verbose packages are at ERROR (not clamped)
    verbose_packages = [
        "docket",
        "httpx",
        "websockets",
        "httpcore",
        "markdown_it",
        "mcp.server.lowlevel",
        "openai",
    ]
    for package in verbose_packages:
        logger = logging.getLogger(package)
        assert logger.level == logging.ERROR


def test_configure_logging_invalid_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test logging configuration with invalid level raises ValueError."""
    # Clear any existing logging configuration
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)

    monkeypatch.setenv("DOCKETEER_LOG_LEVEL", "TRACE")

    with pytest.raises(ValueError, match="Invalid log level: TRACE"):
        configure_logging()


def test_verbose_packages_inheritance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that sub-loggers of verbose packages inherit the clamping."""
    # Clear any existing logging configuration
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)

    monkeypatch.setenv("DOCKETEER_LOG_LEVEL", "DEBUG")

    configure_logging()

    # Test sub-loggers inherit the clamping
    sub_loggers = [
        "httpcore.http11",
        "httpcore.connection",
        "httpcore.proxy",
        "mcp.server.lowlevel.server",
        "openai.api_requestor",
        "openai.resources",
    ]

    for logger_name in sub_loggers:
        logger = logging.getLogger(logger_name)
        # Effective level should be INFO due to parent clamping
        assert logger.getEffectiveLevel() == logging.INFO


def test_regular_loggers_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that regular loggers are not affected by verbose package clamping."""
    # Clear any existing logging configuration
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)

    monkeypatch.setenv("DOCKETEER_LOG_LEVEL", "DEBUG")

    configure_logging()

    # Regular loggers should respect the DEBUG level
    regular_loggers = ["docketeer", "docketeer.brain", "tests"]

    for logger_name in regular_loggers:
        logger = logging.getLogger(logger_name)
        # Effective level should be DEBUG
        assert logger.getEffectiveLevel() == logging.DEBUG


def test_configure_logging_to_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When log_file is provided, logs go to file instead of stderr."""
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)
    monkeypatch.delenv("DOCKETEER_LOG_LEVEL", raising=False)

    log_file = tmp_path / "test.log"
    result = configure_logging(log_file=log_file)

    assert result == log_file

    test_logger = logging.getLogger("test.file_logging")
    test_logger.warning("hello from test")

    for handler in logging.root.handlers:
        handler.flush()

    assert "hello from test" in log_file.read_text()


def test_configure_logging_returns_none_without_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)
    monkeypatch.delenv("DOCKETEER_LOG_LEVEL", raising=False)

    result = configure_logging()
    assert result is None
