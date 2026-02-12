"""Tests for the MCP server wrapping ToolRegistry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.server.lowlevel.server import Server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from docketeer.brain.mcp_server import create_mcp_server
from docketeer.tools import ToolContext, ToolRegistry


@pytest.fixture()
def audit_path(tmp_path: Path) -> Path:
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    return audit_dir


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path)


@pytest.fixture()
def registry_with_tools() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.tool
    async def greet(ctx: ToolContext, name: str) -> str:
        """Say hello.
        name: who to greet
        """
        return f"Hello, {name}!"

    @reg.tool
    async def add(ctx: ToolContext, a: int, b: int) -> str:
        """Add two numbers.
        a: first number
        b: second number
        """
        return str(a + b)

    return reg


def _jsonrpc_request(method: str, params: dict[str, Any], id: int = 1) -> str:
    return json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": id})


async def _run_server_with_requests(
    server: Server,
    requests: list[str],
) -> list[dict[str, Any]]:
    """Run the MCP server with a sequence of JSONRPC requests and collect responses."""
    read_send, read_recv = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](0)
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](0)

    responses: list[dict[str, Any]] = []

    async with anyio.create_task_group() as tg:

        async def feed_requests() -> None:
            async with read_send:
                # First send initialize
                init_req = _jsonrpc_request(
                    "initialize",
                    {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0.1"},
                    },
                    id=0,
                )
                msg = JSONRPCMessage.model_validate_json(init_req)
                await read_send.send(SessionMessage(msg))

                # Wait for the init response to be consumed
                await anyio.sleep(0.05)

                # Send initialized notification
                init_notification = json.dumps(
                    {"jsonrpc": "2.0", "method": "notifications/initialized"}
                )
                msg = JSONRPCMessage.model_validate_json(init_notification)
                await read_send.send(SessionMessage(msg))
                await anyio.sleep(0.05)

                for req in requests:
                    msg = JSONRPCMessage.model_validate_json(req)
                    await read_send.send(SessionMessage(msg))
                    await anyio.sleep(0.05)

        async def collect_responses() -> None:
            async with write_recv:
                async for session_msg in write_recv:
                    data = json.loads(
                        session_msg.message.model_dump_json(
                            by_alias=True, exclude_none=True
                        )
                    )
                    responses.append(data)

        tg.start_soon(feed_requests)
        tg.start_soon(collect_responses)
        opts = server.create_initialization_options()
        await server.run(read_recv, write_send, opts, raise_exceptions=True)

    return responses


async def test_list_tools(
    registry_with_tools: ToolRegistry,
    tool_context: ToolContext,
    audit_path: Path,
):
    server = create_mcp_server(registry_with_tools, tool_context, audit_path)
    req = _jsonrpc_request("tools/list", {})

    responses = await _run_server_with_requests(server, [req])

    # First response is initialize result, second is tools/list result
    tools_response = responses[1]
    assert "result" in tools_response
    tools = tools_response["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"greet", "add"}

    greet_tool = next(t for t in tools if t["name"] == "greet")
    assert "Say hello." in greet_tool["description"]
    assert "name" in greet_tool["inputSchema"]["properties"]


async def test_call_tool(
    registry_with_tools: ToolRegistry,
    tool_context: ToolContext,
    audit_path: Path,
):
    server = create_mcp_server(registry_with_tools, tool_context, audit_path)
    req = _jsonrpc_request(
        "tools/call", {"name": "greet", "arguments": {"name": "World"}}
    )

    responses = await _run_server_with_requests(server, [req])

    call_response = responses[1]
    assert "result" in call_response
    content = call_response["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "Hello, World!"


async def test_call_tool_writes_audit_log(
    registry_with_tools: ToolRegistry,
    tool_context: ToolContext,
    audit_path: Path,
):
    server = create_mcp_server(registry_with_tools, tool_context, audit_path)
    req = _jsonrpc_request(
        "tools/call", {"name": "greet", "arguments": {"name": "World"}}
    )

    await _run_server_with_requests(server, [req])

    audit_files = list(audit_path.glob("*.jsonl"))
    assert len(audit_files) == 1
    record = json.loads(audit_files[0].read_text().strip())
    assert record["tool"] == "greet"
    assert record["args"] == {"name": "World"}
    assert record["is_error"] is False


async def test_call_tool_error(
    tool_context: ToolContext,
    audit_path: Path,
):
    reg = ToolRegistry()

    @reg.tool
    async def fail_tool(ctx: ToolContext) -> str:
        """A tool that fails."""
        raise RuntimeError("boom")

    server = create_mcp_server(reg, tool_context, audit_path)
    req = _jsonrpc_request("tools/call", {"name": "fail_tool", "arguments": {}})

    responses = await _run_server_with_requests(server, [req])

    call_response = responses[1]
    content = call_response["result"]["content"]
    assert content[0]["text"] == "Error: RuntimeError: boom"
    assert call_response["result"]["isError"] is True


async def test_call_tool_error_writes_audit_log(
    tool_context: ToolContext,
    audit_path: Path,
):
    reg = ToolRegistry()

    @reg.tool
    async def fail_tool(ctx: ToolContext) -> str:
        """A tool that fails."""
        raise RuntimeError("boom")

    server = create_mcp_server(reg, tool_context, audit_path)
    req = _jsonrpc_request("tools/call", {"name": "fail_tool", "arguments": {}})

    await _run_server_with_requests(server, [req])

    audit_files = list(audit_path.glob("*.jsonl"))
    assert len(audit_files) == 1
    record = json.loads(audit_files[0].read_text().strip())
    assert record["tool"] == "fail_tool"
    assert record["is_error"] is True


async def test_call_unknown_tool(
    tool_context: ToolContext,
    audit_path: Path,
):
    reg = ToolRegistry()
    server = create_mcp_server(reg, tool_context, audit_path)
    req = _jsonrpc_request("tools/call", {"name": "nonexistent", "arguments": {}})

    responses = await _run_server_with_requests(server, [req])

    call_response = responses[1]
    content = call_response["result"]["content"]
    assert "Unknown tool" in content[0]["text"]
    assert call_response["result"]["isError"] is True


async def test_empty_registry(
    tool_context: ToolContext,
    audit_path: Path,
):
    reg = ToolRegistry()
    server = create_mcp_server(reg, tool_context, audit_path)
    req = _jsonrpc_request("tools/list", {})

    responses = await _run_server_with_requests(server, [req])

    tools_response = responses[1]
    assert tools_response["result"]["tools"] == []
