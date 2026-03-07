"""Shared test fixtures for docketeer-deepinfra tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from docketeer.tools import ToolContext


@pytest.fixture()
def mock_client() -> MagicMock:
    """An OpenAI client mock with chat.completions.create pre-wired as async."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path, username="test-user")
