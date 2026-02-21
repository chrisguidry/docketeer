"""Tests for docketeer.logging module."""

import logging

import pytest

from docketeer.logging import configure_logging


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
    verbose_packages = ["docket", "httpx", "websockets", "httpcore", "openai"]
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
    verbose_packages = ["docket", "httpx", "websockets", "httpcore", "openai"]
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
    verbose_packages = ["docket", "httpx", "websockets", "httpcore", "openai"]
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
    verbose_packages = ["docket", "httpx", "websockets", "httpcore", "openai"]
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
