# docketeer-bubblewrap

Sandboxed command execution for [Docketeer](https://github.com/chrisguidry/docketeer)
using [bubblewrap](https://github.com/containers/bubblewrap) (`bwrap`).

This plugin provides a `CommandExecutor` implementation that runs external
programs inside a lightweight Linux sandbox using unprivileged user namespaces.
Each process gets its own PID, UTS, IPC, and cgroup namespaces, and network
access is denied by default. The `--die-with-parent` flag ensures sandboxed
processes are cleaned up if the parent exits.

## Requirements

- Linux with unprivileged user namespaces enabled
- `bwrap` on `PATH` (install via your distro's `bubblewrap` package)

## How it works

The executor builds a minimal filesystem view inside the sandbox:

- Read-only binds for system directories (`/usr`, `/bin`, `/lib`, `/etc/ssl`, etc.)
- `/proc`, `/dev`, and a tmpfs `/tmp`
- User-specified mounts (read-only or writable)
- Optional network access via `--share-net`
