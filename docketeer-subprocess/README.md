# docketeer-subprocess

Unsandboxed command execution for [Docketeer](https://github.com/chrisguidry/docketeer)
using plain subprocesses.

This plugin provides a `CommandExecutor` implementation that runs external
programs directly as subprocesses of the current process, with no sandboxing.

## When to use this

Use `docketeer-subprocess` instead of `docketeer-bubblewrap` when:

- Running inside a **container** (Docker, Podman, etc.) that already provides
  isolation
- Running on a **non-Linux host** where bubblewrap isn't available (macOS,
  Windows/WSL)
- Running on a **dedicated machine** where the overhead of namespace isolation
  isn't needed
- You don't have unprivileged user namespaces enabled

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKETEER_EXECUTOR` | _(auto)_ | Set to `subprocess` when both executor plugins are installed |

If `docketeer-subprocess` is the only executor plugin installed, it's selected
automatically. If both `docketeer-bubblewrap` and `docketeer-subprocess` are
installed, set `DOCKETEER_EXECUTOR=subprocess` to choose this one.

## How it works

The executor runs commands via `asyncio.create_subprocess_exec` with the
current user's environment. The `CommandExecutor` ABC parameters are handled
as follows:

- **`mounts`** — accepted but not used for filesystem remapping. The first
  mount's `source` is used as the working directory.
- **`network_access`** — ignored (always available)
- **`username`** — ignored (runs as current user)
- **`env`** — merged with `os.environ`, caller values override

The `start_claude` method launches `claude -p` with an MCP bridge that
connects Claude's stdio transport to docketeer's unix socket, the same way
the bubblewrap executor does.
