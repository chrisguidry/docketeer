# docketeer-bubblewrap

Sandboxed command execution via [bubblewrap](https://github.com/containers/bubblewrap)
(`bwrap`). Implements the `docketeer.executor` entry point.

## Structure

- **`executor.py`** — the `BubblewrapExecutor`. Builds `bwrap` command lines
  with mount specs, environment injection, and secret resolution from the
  vault. Handles both `run` (single command) and `shell` (shell string)
  execution modes.
- **`mcp_bridge.py`** — launches MCP servers inside the bubblewrap sandbox,
  bridging stdio transport through the sandbox boundary.

## Testing

Tests mock the `asyncio.create_subprocess_exec` path. No real `bwrap`
invocations happen in tests. Verify the command-line construction, mount
assembly, and secret environment handling.
