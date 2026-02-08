"""Shared test fixtures for docketeer-mcp."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer import environment
from docketeer.tools import ToolContext


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path) -> Iterator[None]:
    """Isolate tests from the real data directory."""
    with patch.object(environment, "DATA_DIR", tmp_path / "data"):
        yield


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, room_id="room1")
