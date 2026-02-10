"""Tests for the MCP agent-facing tools."""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.tools import ToolContext, registry
from docketeer_mcp.manager import MCPClientManager, MCPToolInfo


@pytest.fixture(autouse=True)
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


def _write_server(mcp_dir: Path, name: str, data: dict) -> None:
    (mcp_dir / f"{name}.json").write_text(json.dumps(data))


async def test_list_mcp_servers_none(tool_context: ToolContext, data_dir: Path):
    result = await registry.execute("list_mcp_servers", {}, tool_context)
    assert "No MCP servers configured" in result


async def test_list_mcp_servers_disconnected(tool_context: ToolContext, mcp_dir: Path):
    _write_server(mcp_dir, "time", {"command": "uvx", "args": ["mcp-server-time"]})
    result = await registry.execute("list_mcp_servers", {}, tool_context)
    assert "**time**" in result
    assert "disconnected" in result


async def test_list_mcp_servers_connected(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    _write_server(mcp_dir, "time", {"command": "uvx"})
    fresh_manager._tools["time"] = [
        MCPToolInfo(server="time", name="t1", description="", input_schema={})
    ]
    fresh_manager._clients["time"] = object()  # type: ignore[assignment]

    result = await registry.execute("list_mcp_servers", {}, tool_context)
    assert "connected (1 tools)" in result


async def test_list_mcp_servers_http(tool_context: ToolContext, mcp_dir: Path):
    _write_server(mcp_dir, "api", {"url": "https://example.com/mcp"})
    result = await registry.execute("list_mcp_servers", {}, tool_context)
    assert "https://example.com/mcp" in result


async def test_connect_already_connected(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager._clients["s"] = object()  # type: ignore[assignment]
    result = await registry.execute("connect_mcp_server", {"name": "s"}, tool_context)
    assert "Already connected" in result


async def test_connect_not_configured(tool_context: ToolContext, data_dir: Path):
    result = await registry.execute(
        "connect_mcp_server", {"name": "missing"}, tool_context
    )
    assert "No server configured" in result


async def test_connect_success(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    _write_server(mcp_dir, "time", {"command": "uvx"})
    tools = [
        MCPToolInfo(
            server="time", name="get_time", description="Gets the time", input_schema={}
        )
    ]
    fresh_manager.connect = AsyncMock(return_value=tools)  # type: ignore[method-assign]

    result = await registry.execute(
        "connect_mcp_server", {"name": "time"}, tool_context
    )
    assert "1 tools" in result
    assert "**get_time**" in result


async def test_connect_no_tools(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    _write_server(mcp_dir, "empty", {"command": "echo"})
    fresh_manager.connect = AsyncMock(return_value=[])  # type: ignore[method-assign]

    result = await registry.execute(
        "connect_mcp_server", {"name": "empty"}, tool_context
    )
    assert "no tools found" in result


async def test_connect_failure(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    _write_server(mcp_dir, "bad", {"command": "false"})
    fresh_manager.connect = AsyncMock(side_effect=RuntimeError("connection refused"))  # type: ignore[method-assign]

    result = await registry.execute("connect_mcp_server", {"name": "bad"}, tool_context)
    assert "Failed to connect" in result
    assert "connection refused" in result


async def test_disconnect_not_connected(tool_context: ToolContext):
    result = await registry.execute(
        "disconnect_mcp_server", {"name": "x"}, tool_context
    )
    assert "Not connected" in result


async def test_disconnect_success(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager._clients["s"] = object()  # type: ignore[assignment]
    fresh_manager._tools["s"] = []
    fresh_manager.disconnect = AsyncMock()  # type: ignore[method-assign]

    result = await registry.execute(
        "disconnect_mcp_server", {"name": "s"}, tool_context
    )
    assert "Disconnected" in result


async def test_search_no_results(tool_context: ToolContext):
    result = await registry.execute("search_mcp_tools", {"query": "time"}, tool_context)
    assert "No tools matching" in result


async def test_search_with_results(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager._tools["s"] = [
        MCPToolInfo(
            server="s",
            name="get_time",
            description="Gets the current time",
            input_schema={"type": "object", "properties": {"tz": {"type": "string"}}},
        ),
    ]
    result = await registry.execute("search_mcp_tools", {"query": "time"}, tool_context)
    assert "s / get_time" in result
    assert "Gets the current time" in result
    assert '"tz"' in result


async def test_search_no_description(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager._tools["s"] = [
        MCPToolInfo(server="s", name="bare_tool", description="", input_schema={}),
    ]
    result = await registry.execute("search_mcp_tools", {"query": "bare"}, tool_context)
    assert "bare_tool" in result


async def test_use_tool_success(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager.call_tool = AsyncMock(return_value="42")  # type: ignore[method-assign]

    result = await registry.execute(
        "use_mcp_tool",
        {"server": "s", "tool": "add", "arguments": '{"a": 1, "b": 2}'},
        tool_context,
    )
    assert result == "42"
    fresh_manager.call_tool.assert_called_once_with("s", "add", {"a": 1, "b": 2})  # type: ignore[union-attr]


async def test_use_tool_bad_json(tool_context: ToolContext):
    result = await registry.execute(
        "use_mcp_tool",
        {"server": "s", "tool": "t", "arguments": "not json"},
        tool_context,
    )
    assert "Invalid JSON" in result


async def test_use_tool_error(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager.call_tool = AsyncMock(side_effect=RuntimeError("timeout"))  # type: ignore[method-assign]

    result = await registry.execute(
        "use_mcp_tool",
        {"server": "s", "tool": "t"},
        tool_context,
    )
    assert "Error calling s/t" in result


async def test_add_server_stdio(tool_context: ToolContext, mcp_dir: Path):
    result = await registry.execute(
        "add_mcp_server",
        {
            "name": "time",
            "command": "uvx",
            "args": '["mcp-server-time"]',
            "env": '{"TZ": "UTC"}',
        },
        tool_context,
    )
    assert "Saved server 'time'" in result
    assert "command" in result
    data = json.loads((mcp_dir / "time.json").read_text())
    assert data["command"] == "uvx"


async def test_add_server_http(tool_context: ToolContext, mcp_dir: Path):
    result = await registry.execute(
        "add_mcp_server",
        {"name": "api", "url": "https://example.com/mcp"},
        tool_context,
    )
    assert "Saved server 'api'" in result
    assert "url" in result


async def test_add_server_no_command_or_url(tool_context: ToolContext, data_dir: Path):
    result = await registry.execute("add_mcp_server", {"name": "empty"}, tool_context)
    assert "Must provide either command" in result


async def test_add_server_bad_args_json(tool_context: ToolContext, data_dir: Path):
    result = await registry.execute(
        "add_mcp_server",
        {"name": "t", "command": "echo", "args": "not json"},
        tool_context,
    )
    assert "Invalid args JSON" in result


async def test_add_server_bad_env_json(tool_context: ToolContext, data_dir: Path):
    result = await registry.execute(
        "add_mcp_server",
        {"name": "t", "command": "echo", "env": "{bad}"},
        tool_context,
    )
    assert "Invalid env JSON" in result


async def test_add_server_bad_headers_json(tool_context: ToolContext, data_dir: Path):
    result = await registry.execute(
        "add_mcp_server",
        {"name": "t", "url": "https://x.com", "headers": "nope"},
        tool_context,
    )
    assert "Invalid headers JSON" in result


async def test_add_server_invalid_name(tool_context: ToolContext, data_dir: Path):
    result = await registry.execute(
        "add_mcp_server",
        {"name": "bad name!", "command": "echo"},
        tool_context,
    )
    assert "Invalid server name" in result


async def test_remove_server_exists(tool_context: ToolContext, mcp_dir: Path):
    (mcp_dir / "old.json").write_text("{}")
    result = await registry.execute("remove_mcp_server", {"name": "old"}, tool_context)
    assert "Removed server 'old'" in result
    assert not (mcp_dir / "old.json").exists()


async def test_remove_server_missing(tool_context: ToolContext, data_dir: Path):
    result = await registry.execute("remove_mcp_server", {"name": "gone"}, tool_context)
    assert "No server configured" in result


async def test_remove_server_disconnects_first(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    (mcp_dir / "active.json").write_text("{}")
    fresh_manager._clients["active"] = object()  # type: ignore[assignment]
    fresh_manager._tools["active"] = []
    fresh_manager.disconnect = AsyncMock()  # type: ignore[method-assign]

    result = await registry.execute(
        "remove_mcp_server", {"name": "active"}, tool_context
    )
    assert "Removed" in result
    fresh_manager.disconnect.assert_called_once_with("active")  # type: ignore[union-attr]


async def test_remove_server_cancels_oauth_refresh(
    tool_context: ToolContext, mcp_dir: Path
):
    _write_server(
        mcp_dir, "api", {"url": "https://api.example.com/mcp", "auth": "mcp/api/token"}
    )

    mock_docket = AsyncMock()
    with patch("docketeer_mcp.tools.current_docket", return_value=mock_docket):
        result = await registry.execute(
            "remove_mcp_server", {"name": "api"}, tool_context
        )

    assert "Removed" in result
    mock_docket.cancel.assert_called_once_with("mcp-refresh-mcp/api/token")


async def test_remove_server_cancel_refresh_ignores_errors(
    tool_context: ToolContext, mcp_dir: Path
):
    _write_server(
        mcp_dir, "api", {"url": "https://api.example.com/mcp", "auth": "mcp/api/token"}
    )

    mock_docket = AsyncMock()
    mock_docket.cancel = AsyncMock(side_effect=RuntimeError("no such task"))
    with patch("docketeer_mcp.tools.current_docket", return_value=mock_docket):
        result = await registry.execute(
            "remove_mcp_server", {"name": "api"}, tool_context
        )

    assert "Removed" in result
