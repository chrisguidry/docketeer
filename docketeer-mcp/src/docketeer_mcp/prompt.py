"""System prompt provider for MCP server catalog."""

from pathlib import Path

from docketeer.prompt import SystemBlock

from .config import load_servers
from .manager import manager


def provide_mcp_catalog(workspace: Path) -> list[SystemBlock]:
    """Build an MCP server catalog block for the system prompt."""
    servers = load_servers()
    if not servers:
        return []

    connected = manager.connected_servers()

    lines = [
        "## MCP Servers",
        "",
        "Use `connect_mcp_server` to connect, `search_mcp_tools` to find tools, "
        "and `use_mcp_tool` to call them.",
        "",
        "Configured servers:",
    ]
    for name, cfg in servers.items():
        kind = f"`{cfg.command}`" if cfg.is_stdio else f"`{cfg.url}`"
        lines.append(f"- **{name}**: {kind}")

    if connected:
        parts = [f"{name} ({count} tools)" for name, count in connected.items()]
        lines.append("")
        lines.append(f"Connected: {', '.join(parts)}")

    return [SystemBlock(text="\n".join(lines))]
