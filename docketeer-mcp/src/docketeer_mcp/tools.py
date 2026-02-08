"""Agent-facing MCP tools."""

import json
import logging

from docketeer.tools import ToolContext, registry

from . import config
from .manager import manager

log = logging.getLogger(__name__)


@registry.tool
async def list_mcp_servers(ctx: ToolContext) -> str:
    """List configured MCP servers and their connection status."""
    servers = config.load_servers()
    if not servers:
        return "No MCP servers configured."

    connected = manager.connected_servers()
    lines = []
    for name, cfg in servers.items():
        kind = cfg.command if cfg.is_stdio else cfg.url
        status = (
            f"connected ({connected[name]} tools)"
            if name in connected
            else "disconnected"
        )
        lines.append(f"- **{name}**: `{kind}` — {status}")
    return "\n".join(lines)


@registry.tool
async def connect_mcp_server(ctx: ToolContext, name: str) -> str:
    """Connect to a configured MCP server and discover its tools.

    name: server name from the configuration
    """
    if manager.is_connected(name):
        return f"Already connected to {name!r}."

    servers = config.load_servers()
    cfg = servers.get(name)
    if not cfg:
        return f"No server configured with name {name!r}."

    try:
        tools = await manager.connect(name, cfg, ctx.executor, ctx.workspace)
    except Exception as e:
        log.warning("Failed to connect to MCP server %r", name, exc_info=True)
        return f"Failed to connect to {name!r}: {e}"

    if not tools:
        return f"Connected to {name!r} — no tools found."

    lines = [f"Connected to {name!r} — {len(tools)} tools:"]
    for t in tools:
        lines.append(f"- **{t.name}**: {t.description}")
    return "\n".join(lines)


@registry.tool
async def disconnect_mcp_server(ctx: ToolContext, name: str) -> str:
    """Disconnect from a connected MCP server.

    name: server name to disconnect
    """
    if not manager.is_connected(name):
        return f"Not connected to {name!r}."
    await manager.disconnect(name)
    return f"Disconnected from {name!r}."


@registry.tool
async def search_mcp_tools(ctx: ToolContext, query: str, server: str = "") -> str:
    """Search connected MCP servers for tools matching a query.

    query: search term to match against tool names and descriptions
    server: optional server name to limit the search to
    """
    results = manager.search_tools(query, server=server)
    if not results:
        return f"No tools matching {query!r}."

    lines = []
    for t in results:
        lines.append(f"### {t.server} / {t.name}")
        if t.description:
            lines.append(t.description)
        lines.append(f"```json\n{json.dumps(t.input_schema, indent=2)}\n```")
        lines.append("")
    return "\n".join(lines)


@registry.tool
async def use_mcp_tool(
    ctx: ToolContext, server: str, tool: str, arguments: str = "{}"
) -> str:
    """Call a tool on a connected MCP server.

    server: server name
    tool: tool name on that server
    arguments: JSON string of tool arguments
    """
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return f"Invalid JSON arguments: {e}"

    try:
        return await manager.call_tool(server, tool, args)
    except Exception as e:
        return f"Error calling {server}/{tool}: {e}"


@registry.tool
async def add_mcp_server(
    ctx: ToolContext,
    name: str,
    command: str = "",
    args: str = "[]",
    env: str = "{}",
    url: str = "",
    headers: str = "{}",
    network_access: bool = False,
) -> str:
    """Save a new MCP server configuration.

    name: identifier for the server
    command: executable to run (for stdio servers)
    args: JSON array of command arguments
    env: JSON object of environment variables
    url: server URL (for HTTP servers)
    headers: JSON object of HTTP headers
    network_access: whether the server needs network access (stdio only)
    """
    try:
        args_list = json.loads(args)
    except json.JSONDecodeError as e:
        return f"Invalid args JSON: {e}"

    try:
        env_dict = json.loads(env)
    except json.JSONDecodeError as e:
        return f"Invalid env JSON: {e}"

    try:
        headers_dict = json.loads(headers)
    except json.JSONDecodeError as e:
        return f"Invalid headers JSON: {e}"

    if not command and not url:
        return "Must provide either command (stdio) or url (HTTP)."

    cfg = config.MCPServerConfig(
        name=name,
        command=command,
        args=args_list,
        env=env_dict,
        url=url,
        headers=headers_dict,
        network_access=network_access,
    )
    try:
        config.save_server(cfg)
    except ValueError as e:
        return str(e)

    kind = f"command `{command}`" if command else f"url `{url}`"
    return f"Saved server {name!r} ({kind})."


@registry.tool
async def remove_mcp_server(ctx: ToolContext, name: str) -> str:
    """Remove an MCP server configuration.

    name: server name to remove
    """
    if manager.is_connected(name):
        await manager.disconnect(name)
    if config.remove_server(name):
        return f"Removed server {name!r}."
    return f"No server configured with name {name!r}."
