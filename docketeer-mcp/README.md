# docketeer-mcp

MCP (Model Context Protocol) server support for
[Docketeer](https://github.com/chrisguidry/docketeer). Connects the agent to
any MCP-compatible server so new capabilities are config, not code.

## Tools

| Tool | Purpose |
|------|---------|
| `list_mcp_servers` | Show configured and connected servers |
| `connect_mcp_server` | Connect to a configured server |
| `disconnect_mcp_server` | Disconnect from a server |
| `search_mcp_tools` | Search connected servers' tools by keyword |
| `use_mcp_tool` | Call a tool on a connected server |
| `add_mcp_server` | Save a new server configuration |
| `remove_mcp_server` | Delete a server configuration |

## Configuration

Server configs live in `$DOCKETEER_DATA_DIR/mcp/` as individual JSON files.

### Stdio server

```json
{
  "command": "uvx",
  "args": ["mcp-server-time"],
  "env": {"TZ": "America/New_York"},
  "networkAccess": false
}
```

### HTTP server

```json
{
  "url": "https://weather-api.example.com/mcp",
  "headers": {"Authorization": "Bearer ..."}
}
```

Secrets stay in the data directory, outside the agent-visible workspace.
