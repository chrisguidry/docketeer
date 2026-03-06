"""Tests for the MCP agent-facing tools."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from docketeer.testing import MemoryVault
from docketeer.tools import ToolContext, registry
from docketeer_mcp.manager import MCPClientManager, MCPToolInfo


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
    fresh_manager.connect = AsyncMock(side_effect=ValueError("connection refused"))  # type: ignore[method-assign]

    result = await registry.execute("connect_mcp_server", {"name": "bad"}, tool_context)
    assert "Failed to connect" in result
    assert "connection refused" in result


async def test_connect_mcp_error(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    _write_server(mcp_dir, "bad", {"command": "false"})
    fresh_manager.connect = AsyncMock(  # type: ignore[method-assign]
        side_effect=McpError(ErrorData(code=-1, message="Connection closed")),
    )

    result = await registry.execute("connect_mcp_server", {"name": "bad"}, tool_context)
    assert "Failed to connect" in result
    assert "Connection closed" in result


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
    index = tool_context.search.get_index("mcp-tools")
    await index.index_file("s/get_time", "get_time: Gets the current time")
    fresh_manager._clients["s"] = object()  # type: ignore[assignment]
    fresh_manager._tools["s"] = [
        MCPToolInfo(
            server="s",
            name="get_time",
            description="Gets the current time",
            input_schema={},
        ),
    ]
    result = await registry.execute("search_mcp_tools", {"query": "time"}, tool_context)
    assert "s/get_time" in result
    assert "connected" in result
    assert "Gets the current time" in result


async def test_search_disconnected_server(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    index = tool_context.search.get_index("mcp-tools")
    await index.index_file("s/bare_tool", "bare_tool: does bare things")
    result = await registry.execute("search_mcp_tools", {"query": "bare"}, tool_context)
    assert "bare_tool" in result
    assert "disconnected" in result


async def test_search_filters_by_server(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    index = tool_context.search.get_index("mcp-tools")
    await index.index_file("a/tool1", "tool1: tool on a")
    await index.index_file("b/tool2", "tool2: tool on b")
    result = await registry.execute(
        "search_mcp_tools", {"query": "tool", "server": "a"}, tool_context
    )
    assert "a/tool1" in result
    assert "b/tool2" not in result


async def test_use_tool_success(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager.call_tool = AsyncMock(return_value="42")  # type: ignore[method-assign]

    result = await registry.execute(
        "use_mcp_tool",
        {"server": "s", "tool": "add", "arguments": {"a": 1, "b": 2}},
        tool_context,
    )
    assert result == "42"
    fresh_manager.call_tool.assert_called_once_with("s", "add", {"a": 1, "b": 2})  # type: ignore[union-attr]


async def test_use_tool_empty_dict_arguments(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager.call_tool = AsyncMock(return_value="ok")  # type: ignore[method-assign]

    result = await registry.execute(
        "use_mcp_tool",
        {"server": "s", "tool": "t", "arguments": {}},
        tool_context,
    )
    assert result == "ok"
    fresh_manager.call_tool.assert_called_once_with("s", "t", {})  # type: ignore[union-attr]


async def test_use_tool_error(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager.call_tool = AsyncMock(side_effect=ValueError("timeout"))  # type: ignore[method-assign]

    result = await registry.execute(
        "use_mcp_tool",
        {"server": "s", "tool": "t"},
        tool_context,
    )
    assert "Error calling s/t" in result


async def test_use_tool_string_arguments(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager.call_tool = AsyncMock(return_value="ok")  # type: ignore[method-assign]

    result = await registry.execute(
        "use_mcp_tool",
        {"server": "s", "tool": "t", "arguments": '{"a": 1}'},
        tool_context,
    )
    assert result == "ok"
    fresh_manager.call_tool.assert_called_once_with("s", "t", {"a": 1})  # type: ignore[union-attr]


async def test_use_tool_invalid_json_arguments(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    result = await registry.execute(
        "use_mcp_tool",
        {"server": "s", "tool": "t", "arguments": "not json"},
        tool_context,
    )
    assert "invalid JSON" in result


async def test_use_tool_mcp_error(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager.call_tool = AsyncMock(  # type: ignore[method-assign]
        side_effect=McpError(ErrorData(code=-1, message="Connection closed")),
    )

    result = await registry.execute(
        "use_mcp_tool",
        {"server": "s", "tool": "t"},
        tool_context,
    )
    assert "Error calling s/t" in result
    assert "Connection closed" in result


async def test_add_server_stdio(tool_context: ToolContext, mcp_dir: Path):
    result = await registry.execute(
        "add_mcp_server",
        {
            "name": "time",
            "command": "uvx",
            "args": ["mcp-server-time"],
            "env": {"TZ": "UTC"},
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


# --- secret env resolution ---


async def test_connect_resolves_secret_env(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    _write_server(
        mcp_dir,
        "gw",
        {
            "command": "uvx",
            "env": {
                "TZ": "UTC",
                "CLIENT_ID": {"secret": "mcp/gw/client-id"},
            },
        },
    )
    vault = MemoryVault({"mcp/gw/client-id": "my-client-id"})
    tool_context.vault = vault

    tools = [MCPToolInfo(server="gw", name="t", description="", input_schema={})]
    fresh_manager.connect = AsyncMock(return_value=tools)  # type: ignore[method-assign]

    result = await registry.execute("connect_mcp_server", {"name": "gw"}, tool_context)
    assert "1 tools" in result

    call_kwargs = fresh_manager.connect.call_args.kwargs  # type: ignore[union-attr]
    assert call_kwargs["resolved_env"] == {"TZ": "UTC", "CLIENT_ID": "my-client-id"}


async def test_connect_secret_env_missing_secret(
    tool_context: ToolContext, mcp_dir: Path
):
    _write_server(
        mcp_dir,
        "gw",
        {"command": "uvx", "env": {"KEY": {"secret": "nonexistent"}}},
    )
    vault = MemoryVault()
    tool_context.vault = vault

    result = await registry.execute("connect_mcp_server", {"name": "gw"}, tool_context)
    assert "Could not resolve secret 'nonexistent'" in result


async def test_connect_secret_env_no_vault(tool_context: ToolContext, mcp_dir: Path):
    _write_server(
        mcp_dir,
        "gw",
        {"command": "uvx", "env": {"KEY": {"secret": "vault/path"}}},
    )

    result = await registry.execute("connect_mcp_server", {"name": "gw"}, tool_context)
    assert "no vault" in result


async def test_connect_plain_env_no_vault(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    _write_server(
        mcp_dir,
        "time",
        {"command": "uvx", "env": {"TZ": "UTC"}},
    )
    tools = [MCPToolInfo(server="time", name="t", description="", input_schema={})]
    fresh_manager.connect = AsyncMock(return_value=tools)  # type: ignore[method-assign]

    result = await registry.execute(
        "connect_mcp_server", {"name": "time"}, tool_context
    )
    assert "1 tools" in result
    call_kwargs = fresh_manager.connect.call_args.kwargs  # type: ignore[union-attr]
    assert call_kwargs["resolved_env"] == {"TZ": "UTC"}


async def test_add_server_with_secret_env(tool_context: ToolContext, mcp_dir: Path):
    result = await registry.execute(
        "add_mcp_server",
        {
            "name": "gw",
            "command": "uvx",
            "env": {"TZ": "UTC", "KEY": {"secret": "vault/path"}},
        },
        tool_context,
    )
    assert "Saved server 'gw'" in result
    data = json.loads((mcp_dir / "gw.json").read_text())
    assert data["env"]["TZ"] == "UTC"
    assert data["env"]["KEY"] == {"secret": "vault/path"}
