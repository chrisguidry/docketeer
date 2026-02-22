"""Shared test fixtures for docketeer-mcp."""

from collections.abc import Generator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer import environment
from docketeer.tools import ToolContext
from docketeer_mcp.manager import MCPClientManager


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


@pytest.fixture()
def fresh_manager() -> Generator[MCPClientManager]:
    """Replace the module-level manager with a fresh instance for each test."""
    fresh = MCPClientManager()
    with (
        patch("docketeer_mcp.tools.manager", fresh),
        patch("docketeer_mcp.prompt.manager", fresh),
    ):
        yield fresh


@pytest.fixture()
def data_dir(tmp_path: Path) -> Generator[Path]:
    d = tmp_path / "data"
    d.mkdir()
    with patch("docketeer_mcp.config.environment") as mock_env:
        mock_env.DATA_DIR = d
        yield d


@pytest.fixture()
def mcp_dir(data_dir: Path) -> Path:
    d = data_dir / "mcp"
    d.mkdir()
    return d


@pytest.fixture()
def mock_http() -> Generator[AsyncMock]:
    """Mock httpx.AsyncClient for OAuth tests."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with patch("docketeer_mcp.oauth.httpx.AsyncClient", return_value=mock_client):
        yield mock_client
