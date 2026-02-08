"""Tests for the MCP prompt provider."""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer_mcp.manager import MCPClientManager, MCPToolInfo
from docketeer_mcp.prompt import provide_mcp_catalog


@pytest.fixture(autouse=True)
def fresh_manager() -> Generator[MCPClientManager]:
    fresh = MCPClientManager()
    with patch("docketeer_mcp.prompt.manager", fresh):
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


def test_no_servers(workspace: Path, data_dir: Path):
    assert provide_mcp_catalog(workspace) == []


def test_with_servers_disconnected(workspace: Path, mcp_dir: Path):
    (mcp_dir / "time.json").write_text(
        json.dumps({"command": "uvx", "args": ["mcp-server-time"]})
    )
    (mcp_dir / "api.json").write_text(
        json.dumps({"url": "https://api.example.com/mcp"})
    )

    blocks = provide_mcp_catalog(workspace)
    assert len(blocks) == 1
    text = blocks[0].text
    assert "## MCP Servers" in text
    assert "**time**: `uvx`" in text
    assert "**api**: `https://api.example.com/mcp`" in text
    assert "connect_mcp_server" in text
    assert "Connected:" not in text


def test_with_connected_server(
    workspace: Path, mcp_dir: Path, fresh_manager: MCPClientManager
):
    (mcp_dir / "time.json").write_text(json.dumps({"command": "uvx"}))
    fresh_manager._tools["time"] = [
        MCPToolInfo(server="time", name="t", description="", input_schema={}),
        MCPToolInfo(server="time", name="u", description="", input_schema={}),
    ]
    fresh_manager._clients["time"] = object()  # type: ignore[assignment]

    blocks = provide_mcp_catalog(workspace)
    text = blocks[0].text
    assert "Connected: time (2 tools)" in text
