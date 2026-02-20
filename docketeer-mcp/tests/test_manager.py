"""Tests for the MCPClientManager."""

import logging
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.executor import CommandExecutor, Mount, RunningProcess
from docketeer_mcp.config import MCPServerConfig
from docketeer_mcp.manager import (
    MCPClientManager,
    MCPToolInfo,
    _build_transport,
)
from docketeer_mcp.transport import ExecutorTransport


class FakeExecutor(CommandExecutor):
    async def start(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        mounts: list[Mount] | None = None,
        network_access: bool = False,
        username: str | None = None,
    ) -> RunningProcess:  # pragma: no cover
        raise NotImplementedError


@dataclass
class FakeTool:
    name: str
    description: str | None
    inputSchema: dict


@dataclass
class FakeTextContent:
    text: str


@dataclass
class FakeImageContent:
    data: str
    mimeType: str


@dataclass
class FakeCallResult:
    content: list


def _mock_client(
    tools: list[FakeTool] | None = None, call_result: FakeCallResult | None = None
) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.list_tools = AsyncMock(return_value=tools or [])
    client.call_tool = AsyncMock(return_value=call_result or FakeCallResult(content=[]))
    return client


# --- _build_transport tests ---


def test_build_transport_stdio_with_executor(tmp_path: Path):
    config = MCPServerConfig(
        name="t", command="uvx", args=["server"], network_access=True
    )
    executor = FakeExecutor()
    workspace = Path("/ws")
    with patch("docketeer_mcp.manager._mcp_dir", return_value=tmp_path):
        transport = _build_transport(
            config, executor, workspace, resolved_env={"K": "V"}
        )
    assert isinstance(transport, ExecutorTransport)
    assert transport._command == ["uvx", "server"]
    assert transport._env == {"K": "V"}
    assert transport._network_access is True
    persistent_home = tmp_path / "t" / "home"
    assert transport._mounts == [
        Mount(source=Path("/ws"), target=Path("/workspace")),
        Mount(source=persistent_home, target=Path("/home/sandbox"), writable=True),
    ]


def test_build_transport_stdio_with_executor_no_workspace(tmp_path: Path):
    config = MCPServerConfig(name="t", command="echo")
    executor = FakeExecutor()
    with patch("docketeer_mcp.manager._mcp_dir", return_value=tmp_path):
        transport = _build_transport(config, executor)
    assert isinstance(transport, ExecutorTransport)
    persistent_home = tmp_path / "t" / "home"
    assert transport._mounts == [
        Mount(source=persistent_home, target=Path("/home/sandbox"), writable=True),
    ]


def test_build_transport_stdio_with_executor_empty_env(tmp_path: Path):
    config = MCPServerConfig(name="t", command="echo")
    executor = FakeExecutor()
    with patch("docketeer_mcp.manager._mcp_dir", return_value=tmp_path):
        transport = _build_transport(config, executor)
    assert isinstance(transport, ExecutorTransport)
    assert transport._env is None


def test_build_transport_creates_persistent_home(tmp_path: Path):
    config = MCPServerConfig(name="my-server", command="echo")
    executor = FakeExecutor()
    with patch("docketeer_mcp.manager._mcp_dir", return_value=tmp_path):
        _build_transport(config, executor)
    persistent_home = tmp_path / "my-server" / "home"
    assert persistent_home.is_dir()


def test_build_transport_stdio_without_executor(caplog: pytest.LogCaptureFixture):
    config = MCPServerConfig(name="test", command="python", args=["-m", "server"])
    with caplog.at_level(logging.WARNING):
        transport = _build_transport(config)
    assert "without sandbox" in caplog.text
    from fastmcp.client.transports.stdio import StdioTransport

    assert isinstance(transport, StdioTransport)


def test_build_transport_stdio_without_executor_empty_env():
    config = MCPServerConfig(name="test", command="python")
    transport = _build_transport(config)
    from fastmcp.client.transports.stdio import StdioTransport

    assert isinstance(transport, StdioTransport)


def test_build_transport_http():
    config = MCPServerConfig(
        name="api",
        url="https://example.com/mcp",
        headers={"Authorization": "Bearer tok"},
    )
    transport = _build_transport(config)
    from fastmcp.client.transports import StreamableHttpTransport

    assert isinstance(transport, StreamableHttpTransport)


def test_build_transport_http_no_headers():
    config = MCPServerConfig(name="api", url="https://example.com/mcp")
    transport = _build_transport(config)
    from fastmcp.client.transports import StreamableHttpTransport

    assert isinstance(transport, StreamableHttpTransport)


def test_build_transport_invalid():
    config = MCPServerConfig(name="bad")
    with pytest.raises(ValueError, match="neither command nor url"):
        _build_transport(config)


# --- MCPClientManager tests ---


@pytest.fixture()
def mgr() -> MCPClientManager:
    return MCPClientManager()


async def test_connect_discovers_tools(mgr: MCPClientManager):
    tools = [
        FakeTool(
            name="get_time",
            description="Get current time",
            inputSchema={"type": "object"},
        ),
        FakeTool(name="convert", description=None, inputSchema={}),
    ]
    client = _mock_client(tools)
    config = MCPServerConfig(name="time", command="echo")

    with patch("docketeer_mcp.manager.Client", return_value=client):
        result = await mgr.connect("time", config)

    assert len(result) == 2
    assert result[0].name == "get_time"
    assert result[0].description == "Get current time"
    assert result[1].description == ""
    assert mgr.is_connected("time")


async def test_connect_already_connected(mgr: MCPClientManager):
    client = _mock_client()
    config = MCPServerConfig(name="s", command="echo")

    with patch("docketeer_mcp.manager.Client", return_value=client):
        await mgr.connect("s", config)

    with pytest.raises(ValueError, match="Already connected"):
        await mgr.connect("s", config)


async def test_connect_list_tools_failure_cleans_up(mgr: MCPClientManager):
    client = _mock_client()
    client.list_tools = AsyncMock(side_effect=RuntimeError("boom"))
    config = MCPServerConfig(name="bad", command="echo")

    with patch("docketeer_mcp.manager.Client", return_value=client):
        with pytest.raises(RuntimeError, match="boom"):
            await mgr.connect("bad", config)

    assert not mgr.is_connected("bad")
    client.__aexit__.assert_called_once()


async def test_disconnect(mgr: MCPClientManager):
    client = _mock_client()
    config = MCPServerConfig(name="s", command="echo")

    with patch("docketeer_mcp.manager.Client", return_value=client):
        await mgr.connect("s", config)

    await mgr.disconnect("s")
    assert not mgr.is_connected("s")
    assert client.__aexit__.call_count == 1


async def test_disconnect_not_connected(mgr: MCPClientManager):
    await mgr.disconnect("nonexistent")


async def test_disconnect_all(mgr: MCPClientManager):
    clients = {}
    for name in ("a", "b"):
        client = _mock_client()
        clients[name] = client
        config = MCPServerConfig(name=name, command="echo")
        with patch("docketeer_mcp.manager.Client", return_value=client):
            await mgr.connect(name, config)

    await mgr.disconnect_all()
    assert not mgr.is_connected("a")
    assert not mgr.is_connected("b")


async def test_connected_servers(mgr: MCPClientManager):
    tools_a = [FakeTool("t1", "desc", {}), FakeTool("t2", "desc", {})]
    tools_b = [FakeTool("t3", "desc", {})]

    for name, tools in [("a", tools_a), ("b", tools_b)]:
        client = _mock_client(tools)
        config = MCPServerConfig(name=name, command="echo")
        with patch("docketeer_mcp.manager.Client", return_value=client):
            await mgr.connect(name, config)

    servers = mgr.connected_servers()
    assert servers == {"a": 2, "b": 1}


async def test_search_tools_by_name(mgr: MCPClientManager):
    mgr._tools["s"] = [
        MCPToolInfo(
            server="s", name="get_time", description="Gets the time", input_schema={}
        ),
        MCPToolInfo(
            server="s", name="set_alarm", description="Sets an alarm", input_schema={}
        ),
    ]
    results = mgr.search_tools("time")
    assert len(results) == 1
    assert results[0].name == "get_time"


async def test_search_tools_by_description(mgr: MCPClientManager):
    mgr._tools["s"] = [
        MCPToolInfo(
            server="s", name="foo", description="Fetches weather data", input_schema={}
        ),
    ]
    results = mgr.search_tools("weather")
    assert len(results) == 1


async def test_search_tools_case_insensitive(mgr: MCPClientManager):
    mgr._tools["s"] = [
        MCPToolInfo(server="s", name="GetTime", description="", input_schema={}),
    ]
    results = mgr.search_tools("gettime")
    assert len(results) == 1


async def test_search_tools_filter_by_server(mgr: MCPClientManager):
    mgr._tools["a"] = [
        MCPToolInfo(server="a", name="tool1", description="", input_schema={})
    ]
    mgr._tools["b"] = [
        MCPToolInfo(server="b", name="tool2", description="", input_schema={})
    ]
    results = mgr.search_tools("tool", server="a")
    assert len(results) == 1
    assert results[0].server == "a"


async def test_search_tools_no_match(mgr: MCPClientManager):
    mgr._tools["s"] = [
        MCPToolInfo(server="s", name="x", description="y", input_schema={})
    ]
    assert mgr.search_tools("zzz") == []


async def test_call_tool_text_result(mgr: MCPClientManager):
    result = FakeCallResult(content=[FakeTextContent(text="hello")])
    client = _mock_client(call_result=result)
    mgr._clients["s"] = client

    output = await mgr.call_tool("s", "greet", {"name": "Chris"})
    assert output == "hello"
    client.call_tool.assert_called_once_with("greet", {"name": "Chris"})


async def test_call_tool_non_text_result(mgr: MCPClientManager):
    result = FakeCallResult(
        content=[FakeImageContent(data="abc", mimeType="image/png")]
    )
    client = _mock_client(call_result=result)
    mgr._clients["s"] = client

    output = await mgr.call_tool("s", "screenshot", {})
    assert "FakeImageContent" in output


async def test_call_tool_not_connected(mgr: MCPClientManager):
    with pytest.raises(ValueError, match="Not connected"):
        await mgr.call_tool("missing", "tool", {})
