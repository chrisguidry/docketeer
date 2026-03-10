"""Workspace hook for the mcp/ directory."""

import logging
from pathlib import Path, PurePosixPath

from docketeer.hooks import HookResult, parse_frontmatter

from .config import remove_tool_catalog
from .manager import manager

log = logging.getLogger(__name__)


class MCPHook:
    """Workspace hook for MCP server configuration files.

    Validates frontmatter in mcp/*.md files and handles cleanup when
    server config files are deleted.
    """

    prefix = PurePosixPath("mcp")

    def _is_config_file(self, path: PurePosixPath) -> bool:
        """Check if this is a top-level .md file in mcp/."""
        return path.name.endswith(".md") and len(path.parts) <= 2

    async def validate(self, path: PurePosixPath, content: str) -> HookResult | None:
        """Parse and validate MCP server frontmatter."""
        if not self._is_config_file(path):
            return None

        meta, _ = parse_frontmatter(content)
        if not meta:
            raise ValueError(
                f"MCP config {path} needs YAML frontmatter with "
                f"'command' (stdio) or 'url' (HTTP)"
            )

        name = path.stem
        has_command = bool(meta.get("command"))
        has_url = bool(meta.get("url"))

        if not has_command and not has_url:
            raise ValueError(
                f"MCP config '{name}' must have either 'command' (stdio) or 'url' (HTTP)"
            )

        kind = f"command `{meta['command']}`" if has_command else f"url `{meta['url']}`"
        return HookResult(f"Configured server '{name}' ({kind})")

    async def commit(self, path: PurePosixPath, content: str) -> None:
        """No-op — config.load_servers reads workspace files directly."""

    async def on_delete(self, path: PurePosixPath) -> str | None:
        """Clean up when a server config is deleted."""
        if not self._is_config_file(path):
            return None

        name = path.stem

        if manager.is_connected(name):
            await manager.disconnect(name)

        await manager.deindex_server(name)
        remove_tool_catalog(name)

        return f"Removed server '{name}'"

    async def scan(self, workspace: Path) -> None:
        """No-op — configs are lazy-loaded when connect is called."""


def create_hook() -> MCPHook:
    """Factory for hook discovery via entry points."""
    return MCPHook()
