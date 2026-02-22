# docketeer-mcp

[MCP](https://modelcontextprotocol.io/) server support. This is one of the
larger plugins — it registers `docketeer.tools`, `docketeer.prompt`, and
`docketeer.tasks` entry points.

## Structure

- **`config.py`** — reads MCP server configuration from the workspace
  (`mcp.json`). Defines the schema for server entries.
- **`manager.py`** — the `MCPManager`. Manages MCP client sessions, handles
  connection lifecycle, and proxies tool calls to connected servers.
- **`transport.py`** — custom transport layer for launching MCP servers,
  including sandbox-aware stdio transport via the executor.
- **`oauth.py`** — OAuth flow support for MCP servers that require
  authentication. Handles token storage and refresh.
- **`tools.py`** — tool functions exposed to the agent: connect to servers,
  list available MCP tools, call MCP tools, manage server config.
- **`prompt.py`** — prompt provider that injects the MCP server catalog.
- **`tasks.py`** — background tasks for MCP server health and reconnection.

## Testing

Tests are split by concern: config parsing, manager lifecycle, OAuth flows,
tool invocation, transport, and prompt generation.

The `conftest.py` provides shared fixtures: `data_dir`, `mcp_dir`,
`fresh_manager`, `tool_context`, and the `_write_server` helper. Use these
rather than redefining them in individual test files. OAuth tests use
`MemoryVault` from `docketeer.testing` for token storage.
