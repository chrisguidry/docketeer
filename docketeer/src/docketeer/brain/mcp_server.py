"""MCP server that exposes the host ToolRegistry to a guest Claude Code process."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.lowlevel import Server
from mcp.types import TextContent, Tool

from docketeer.audit import audit_log

if TYPE_CHECKING:
    from docketeer.tools import ToolContext, ToolRegistry

log = logging.getLogger(__name__)


def create_mcp_server(
    registry: ToolRegistry,
    tool_context: ToolContext,
    audit_path: Path,
) -> Server:
    """Build an MCP Server backed by a ToolRegistry.

    The returned Server has list_tools and call_tool handlers that delegate
    to the registry.  The caller is responsible for running it with a transport.
    """
    server = Server("docketeer")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=td.name,
                description=td.description,
                inputSchema=td.input_schema,
            )
            for td in registry.definitions()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = await registry.execute(name, arguments, tool_context)
        is_error = result.startswith("Unknown tool:") or result.startswith("Error:")
        audit_log(audit_path, name, arguments, result, is_error)
        if is_error:
            raise Exception(result)
        return [TextContent(type="text", text=result)]

    return server
