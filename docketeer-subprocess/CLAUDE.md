# docketeer-subprocess

Unsandboxed subprocess command execution. Implements the `docketeer.executor`
entry point for environments where bubblewrap is unavailable or redundant.

## Structure

- **`executor.py`** — the `SubprocessExecutor`. Runs commands as plain
  subprocesses. Uses the first mount's `source` as `cwd`. Ignores sandbox
  parameters (network_access, username, mounts for remapping).
- **`mcp_bridge.py`** — copied from bubblewrap, bridges Claude's stdio-based
  MCP transport to the docketeer unix socket. Stdlib-only.

## Testing

Tests mock `asyncio.create_subprocess_exec`. No real subprocesses are spawned
in tests. Verify cwd selection, env merging, and claude arg construction.
