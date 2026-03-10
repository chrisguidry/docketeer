# docketeer-mcp

[MCP](https://modelcontextprotocol.io/) server support. This is one of the
larger plugins — it registers `docketeer.tools`, `docketeer.prompt`,
`docketeer.tasks`, and `docketeer.hooks` entry points.

## Structure

- **`config.py`** — reads MCP server configuration from workspace `mcp/*.md`
  files with YAML frontmatter. Also handles backstage tool catalog persistence
  at `DATA_DIR/mcp/catalogs/`.
- **`hook.py`** — `MCPHook` workspace hook for the `mcp/` directory. Validates
  frontmatter on write, cleans up (disconnect, deindex, remove catalog) on
  delete. Commit and scan are no-ops since configs are lazy-loaded at connect
  time.
- **`manager.py`** — the `MCPClientManager`. Manages MCP client sessions,
  handles connection lifecycle, and proxies tool calls to connected servers.
- **`transport.py`** — custom transport layer for launching MCP servers,
  including sandbox-aware stdio transport via the executor.
- **`oauth.py`** — OAuth flow support for MCP servers that require
  authentication. Handles token storage and refresh.
- **`tools.py`** — tool functions exposed to the agent: connect to servers,
  list available MCP tools, call MCP tools. Server configuration is done via
  workspace file operations (`write_file`/`delete_file` on `mcp/*.md`).
- **`prompt.py`** — prompt provider that injects the MCP server catalog.
- **`tasks.py`** — background tasks for OAuth token refresh.

## Server configuration format

Servers are configured as workspace markdown files at `mcp/{name}.md` with
YAML frontmatter:

```yaml
---
command: npx
args: ["-y", "@modelcontextprotocol/server-github"]
env:
  GITHUB_TOKEN:
    secret: github/token
network_access: true
---
Optional notes about this server.
```

HTTP variant uses `url` instead of `command`/`args`.

## Testing

Tests are split by concern: config parsing, hook behavior, manager lifecycle,
OAuth flows, tool invocation, transport, and prompt generation.

The `conftest.py` provides shared fixtures: `data_dir`, `mcp_dir`,
`fresh_manager`, `tool_context`, and `workspace`. Test files define local
`_write_server` helpers that write workspace markdown. OAuth tests use
`MemoryVault` from `docketeer.testing` for token storage.
