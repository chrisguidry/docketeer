"""Tests for the MCP agent-facing tools."""

from pathlib import Path
from unittest.mock import AsyncMock

from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from docketeer.testing import MemoryVault
from docketeer.tools import ToolContext, registry
from docketeer_mcp.manager import MCPClientManager, MCPToolInfo


def _write_server(workspace: Path, name: str, content: str) -> None:
    mcp_dir = workspace / "mcp"
    mcp_dir.mkdir(exist_ok=True)
    (mcp_dir / f"{name}.md").write_text(content)


async def test_list_mcp_servers_none(tool_context: ToolContext):
    result = await registry.execute("list_mcp_servers", {}, tool_context)
    assert "No MCP servers configured" in result


async def test_list_mcp_servers_disconnected(
    tool_context: ToolContext, workspace: Path
):
    _write_server(
        workspace, "time", "---\ncommand: uvx\nargs: [mcp-server-time]\n---\n"
    )
    result = await registry.execute("list_mcp_servers", {}, tool_context)
    assert "**time**" in result
    assert "disconnected" in result


async def test_list_mcp_servers_connected(
    tool_context: ToolContext, workspace: Path, fresh_manager: MCPClientManager
):
    _write_server(workspace, "time", "---\ncommand: uvx\n---\n")
    fresh_manager._tools["time"] = [
        MCPToolInfo(server="time", name="t1", description="", input_schema={})
    ]
    fresh_manager._clients["time"] = object()  # type: ignore[assignment]

    result = await registry.execute("list_mcp_servers", {}, tool_context)
    assert "connected (1 tools)" in result


async def test_list_mcp_servers_http(tool_context: ToolContext, workspace: Path):
    _write_server(workspace, "api", "---\nurl: https://example.com/mcp\n---\n")
    result = await registry.execute("list_mcp_servers", {}, tool_context)
    assert "https://example.com/mcp" in result


async def test_connect_already_connected(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    fresh_manager._clients["s"] = object()  # type: ignore[assignment]
    result = await registry.execute("connect_mcp_server", {"name": "s"}, tool_context)
    assert "Already connected" in result


async def test_connect_not_configured(tool_context: ToolContext):
    result = await registry.execute(
        "connect_mcp_server", {"name": "missing"}, tool_context
    )
    assert "No server configured" in result


async def test_connect_success(
    tool_context: ToolContext, workspace: Path, fresh_manager: MCPClientManager
):
    _write_server(workspace, "time", "---\ncommand: uvx\n---\n")
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
    tool_context: ToolContext, workspace: Path, fresh_manager: MCPClientManager
):
    _write_server(workspace, "empty", "---\ncommand: echo\n---\n")
    fresh_manager.connect = AsyncMock(return_value=[])  # type: ignore[method-assign]

    result = await registry.execute(
        "connect_mcp_server", {"name": "empty"}, tool_context
    )
    assert "no tools found" in result


async def test_connect_failure(
    tool_context: ToolContext, workspace: Path, fresh_manager: MCPClientManager
):
    _write_server(workspace, "bad", "---\ncommand: 'false'\n---\n")
    fresh_manager.connect = AsyncMock(side_effect=ValueError("connection refused"))  # type: ignore[method-assign]

    result = await registry.execute("connect_mcp_server", {"name": "bad"}, tool_context)
    assert "Failed to connect" in result
    assert "connection refused" in result


async def test_connect_mcp_error(
    tool_context: ToolContext, workspace: Path, fresh_manager: MCPClientManager
):
    _write_server(workspace, "bad", "---\ncommand: 'false'\n---\n")
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
    await index.index("s/get_time", "get_time: Gets the current time")
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
    assert "1 result(s):" in result
    assert "s/get_time" in result
    assert "connected" in result
    assert "score:" in result
    assert "Gets the current time" in result


async def test_search_disconnected_server(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    index = tool_context.search.get_index("mcp-tools")
    await index.index("s/bare_tool", "bare_tool: does bare things")
    result = await registry.execute("search_mcp_tools", {"query": "bare"}, tool_context)
    assert "bare_tool" in result
    assert "disconnected" in result


async def test_search_filters_by_server(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    index = tool_context.search.get_index("mcp-tools")
    await index.index("a/tool1", "tool1: tool on a")
    await index.index("b/tool2", "tool2: tool on b")
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


# --- secret env resolution ---


async def test_connect_resolves_secret_env(
    tool_context: ToolContext, workspace: Path, fresh_manager: MCPClientManager
):
    _write_server(
        workspace,
        "gw",
        "---\ncommand: uvx\nenv:\n  TZ: UTC\n  CLIENT_ID:\n    secret: mcp/gw/client-id\n---\n",
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
    tool_context: ToolContext, workspace: Path
):
    _write_server(
        workspace,
        "gw",
        "---\ncommand: uvx\nenv:\n  KEY:\n    secret: nonexistent\n---\n",
    )
    vault = MemoryVault()
    tool_context.vault = vault

    result = await registry.execute("connect_mcp_server", {"name": "gw"}, tool_context)
    assert "Could not resolve secret 'nonexistent'" in result


async def test_connect_secret_env_no_vault(tool_context: ToolContext, workspace: Path):
    _write_server(
        workspace,
        "gw",
        "---\ncommand: uvx\nenv:\n  KEY:\n    secret: vault/path\n---\n",
    )

    result = await registry.execute("connect_mcp_server", {"name": "gw"}, tool_context)
    assert "no vault" in result


async def test_connect_plain_env_no_vault(
    tool_context: ToolContext, workspace: Path, fresh_manager: MCPClientManager
):
    _write_server(
        workspace,
        "time",
        "---\ncommand: uvx\nenv:\n  TZ: UTC\n---\n",
    )
    tools = [MCPToolInfo(server="time", name="t", description="", input_schema={})]
    fresh_manager.connect = AsyncMock(return_value=tools)  # type: ignore[method-assign]

    result = await registry.execute(
        "connect_mcp_server", {"name": "time"}, tool_context
    )
    assert "1 tools" in result
    call_kwargs = fresh_manager.connect.call_args.kwargs  # type: ignore[union-attr]
    assert call_kwargs["resolved_env"] == {"TZ": "UTC"}
