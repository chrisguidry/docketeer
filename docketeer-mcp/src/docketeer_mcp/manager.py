"""MCP client manager — connections, tool catalog, and dispatch."""

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import ClientTransport, StreamableHttpTransport
from fastmcp.client.transports.stdio import StdioTransport
from mcp.types import TextContent

from docketeer.executor import CommandExecutor, Mount
from docketeer.search import NullCatalog, SearchCatalog

from .config import (
    CachedToolInfo,
    MCPServerConfig,
    _mcp_dir,
    load_all_tool_catalogs,
    save_tool_catalog,
)
from .oauth import PendingOAuth
from .transport import ExecutorTransport

log = logging.getLogger(__name__)


@dataclass
class MCPToolInfo:
    """Metadata for a single tool on a connected MCP server."""

    server: str
    name: str
    description: str
    input_schema: dict


def _build_transport(
    config: MCPServerConfig,
    executor: CommandExecutor | None = None,
    workspace: Path | None = None,
    auth: str | None = None,
    resolved_env: dict[str, str] | None = None,
) -> ClientTransport:
    """Build the appropriate transport for a server config."""
    if config.is_stdio:
        command = [config.command, *config.args]
        env = resolved_env or None
        if executor:
            mounts: list[Mount] = []
            if workspace:
                mounts.append(Mount(source=workspace, target=Path("/workspace")))
            persistent_home = _mcp_dir() / config.name / "home"
            persistent_home.mkdir(parents=True, exist_ok=True)
            mounts.append(
                Mount(
                    source=persistent_home, target=Path("/home/sandbox"), writable=True
                )
            )
            return ExecutorTransport(
                executor=executor,
                command=command,
                env=env,
                mounts=mounts or None,
                network_access=config.network_access,
            )
        log.warning(
            "No executor available — running MCP server %r without sandbox",
            config.name,
        )
        return StdioTransport(
            command=config.command,
            args=config.args,
            env=env,
        )

    if config.is_http:
        return StreamableHttpTransport(
            url=config.url,
            headers=config.headers or None,
            auth=auth,
        )

    raise ValueError(f"Server {config.name!r} has neither command nor url")


class MCPClientManager:
    """Manages connections to MCP servers and their tool catalogs."""

    def __init__(self, search: SearchCatalog | None = None) -> None:
        self._clients: dict[str, Client] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._tools: dict[str, list[MCPToolInfo]] = {}
        self._pending_oauth: dict[str, PendingOAuth] = {}
        self._search = search or NullCatalog()
        self._reindexed = False

    def set_search(self, search: SearchCatalog) -> None:
        """Wire in a search catalog after construction."""
        self._search = search

    async def connect(
        self,
        name: str,
        config: MCPServerConfig,
        executor: CommandExecutor | None = None,
        workspace: Path | None = None,
        auth: str | None = None,
        resolved_env: dict[str, str] | None = None,
    ) -> list[MCPToolInfo]:
        """Connect to a server and discover its tools."""
        if name in self._clients:
            raise ValueError(f"Already connected to {name!r}")

        transport = _build_transport(
            config, executor, workspace, auth=auth, resolved_env=resolved_env
        )
        client = Client(transport)
        stack = AsyncExitStack()
        await stack.enter_async_context(client)

        try:
            raw_tools = await client.list_tools()
        except Exception:
            await stack.aclose()
            raise

        tools = [
            MCPToolInfo(
                server=name,
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema,
            )
            for t in raw_tools
        ]
        self._clients[name] = client
        self._stacks[name] = stack
        self._tools[name] = tools

        # Cache tool catalog and index for semantic search
        cached = [CachedToolInfo(name=t.name, description=t.description) for t in tools]
        save_tool_catalog(name, cached)
        await self._index_tools(name, cached)

        return tools

    async def disconnect(self, name: str) -> None:
        """Disconnect from a server."""
        self._clients.pop(name, None)
        self._tools.pop(name, None)
        stack = self._stacks.pop(name, None)
        if stack:
            await stack.aclose()

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""
        for name in list(self._clients):
            await self.disconnect(name)

    def is_connected(self, name: str) -> bool:
        return name in self._clients

    def connected_servers(self) -> dict[str, int]:
        """Return connected server names with their tool counts."""
        return {name: len(tools) for name, tools in self._tools.items()}

    def search_tools(self, query: str, server: str = "") -> list[MCPToolInfo]:
        """Search tools by substring match on name or description."""
        query_lower = query.lower()
        results: list[MCPToolInfo] = []
        sources = (
            {server: self._tools[server]}
            if server and server in self._tools
            else self._tools
        )
        for tools in sources.values():
            for tool in tools:
                if (
                    query_lower in tool.name.lower()
                    or query_lower in tool.description.lower()
                ):
                    results.append(tool)
        return results

    async def call_tool(self, server: str, tool: str, arguments: dict) -> str:
        """Call a tool on a connected server, returning the result as a string."""
        client = self._clients.get(server)
        if not client:
            raise ValueError(f"Not connected to server {server!r}")

        result = await client.call_tool(tool, arguments)
        parts = []
        for block in result.content:
            if isinstance(block, TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)

    async def reindex_from_cache(self) -> None:
        """Load all cached tool catalogs and index them for semantic search."""
        if self._reindexed:
            return
        catalogs = load_all_tool_catalogs()
        for server_name, tools in catalogs.items():
            await self._index_tools(server_name, tools)
        self._reindexed = True

    async def deindex_server(self, name: str) -> None:
        """Remove all indexed tools for a server from the search index."""
        index = self._search.get_index("mcp-tools")
        catalog = load_all_tool_catalogs().get(name, [])
        for tool in catalog:
            await index.deindex(f"{name}/{tool.name}")

    async def _index_tools(self, name: str, tools: list[CachedToolInfo]) -> None:
        """Index a server's tools for semantic search."""
        index = self._search.get_index("mcp-tools")
        for tool in tools:
            await index.index(
                f"{name}/{tool.name}",
                f"{tool.name}: {tool.description}",
            )


manager = MCPClientManager()
