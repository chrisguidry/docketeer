"""Tests for the MCP prompt provider."""

from pathlib import Path

from docketeer_mcp.manager import MCPClientManager, MCPToolInfo
from docketeer_mcp.prompt import provide_mcp_catalog


def test_no_servers(workspace: Path):
    assert provide_mcp_catalog(workspace) == []


def test_with_servers_disconnected(workspace: Path):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "time.md").write_text(
        "---\ncommand: uvx\nargs: [mcp-server-time]\n---\n"
    )
    (mcp_dir / "api.md").write_text("---\nurl: https://api.example.com/mcp\n---\n")

    blocks = provide_mcp_catalog(workspace)
    assert len(blocks) == 1
    text = blocks[0].text
    assert "## MCP Servers" in text
    assert "**time**: `uvx`" in text
    assert "**api**: `https://api.example.com/mcp`" in text
    assert "connect_mcp_server" in text
    assert "list_secrets" in text
    assert '{"secret": "path"}' in text
    assert "Connected:" not in text


def test_with_connected_server(workspace: Path, fresh_manager: MCPClientManager):
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "time.md").write_text("---\ncommand: uvx\n---\n")
    fresh_manager._tools["time"] = [
        MCPToolInfo(server="time", name="t", description="", input_schema={}),
        MCPToolInfo(server="time", name="u", description="", input_schema={}),
    ]
    fresh_manager._clients["time"] = object()  # type: ignore[assignment]

    blocks = provide_mcp_catalog(workspace)
    text = blocks[0].text
    assert "Connected: time (2 tools)" in text
