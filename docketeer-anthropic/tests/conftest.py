"""Shared test fixtures for docketeer-anthropic plugin tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from docketeer.tools import ToolContext


@pytest.fixture()
def mock_client() -> MagicMock:
    """Create a mock Anthropic client."""
    client = MagicMock()
    client.messages = MagicMock()
    return client


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    """Create a test tool context."""
    return ToolContext(workspace=tmp_path, username="test-user")
