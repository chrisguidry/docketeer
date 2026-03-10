# docketeer (core)

This is the core engine. Everything else in the workspace depends on it, so
changes here can break any downstream plugin. Be careful and run affected
plugin tests when modifying public interfaces.

## Key modules

- **`brain/`** — the agentic loop. `core.py` orchestrates turns,
  `backend.py` defines the inference backend protocol, `compaction.py`
  handles conversation compaction, `helpers.py` has shared utilities.
  `mcp_server.py` and `mcp_transport.py` expose the agent's tools as an MCP
  server.
- **`chat.py`** — the `ChatClient` ABC. Chat backends (rocketchat, tui)
  implement this. Also defines `IncomingMessage`, `RoomMessage`, `RoomInfo`.
- **`vault.py`** — the `Vault` ABC and vault tools. Vault plugins (1password)
  implement this.
- **`executor.py`** — the `CommandExecutor` ABC and executor tools (run,
  shell). Executor plugins (bubblewrap) implement this.
- **`workspace.py`** — workspace file tools (list, read, write, edit, delete,
  search, links) with hook integration for file-based configuration.
- **`tools.py`** — tool registry infrastructure (`ToolRegistry`, `ToolContext`,
  `ToolDefinition`, `safe_path`). Domain tools are registered lazily from
  their domain modules at import time.
- **`hooks.py`** — workspace hook protocol and registry. Hooks react to file
  operations in special directories (tunings/, tasks/) via validate/commit
  phases.
- **`plugins.py`** — entry point discovery. `discover_one()` for single-select
  plugins, `discover_all()` for multi-load.
- **`tools/`** — built-in tool implementations (workspace files, vault,
  executor). The `__init__.py` has the tool registry and `ToolContext`.
- **`plugins.py`** — entry point discovery. `discover_one()` for auto-selected
  single-select plugins, `discover_explicit()` for optional single-select
  plugins that stay disabled until explicitly configured, `discover_all()` for
  multi-load.
- **`prompt.py`** — system prompt assembly from prompt providers.
- **`tasks.py`** — Docket task definitions (nudge) and the `SchedulingHook`
  for file-based task scheduling.
- **`handlers.py`** — message handling and the bridge between chat and brain.
- **`antenna.py`** — the realtime event feed system. Defines the `Band` ABC,
  `Signal`, `SignalFilter`, `Tuning` data types, filter evaluation, the
  `Antenna` orchestrator, `AntennaHook` for file-based tuning, and the
  `list_bands` tool.
- **`signal_loop.py`** — runs one async task per tuning, filtering signals
  and delivering batches to lines via `brain.process()`.

- **`environment.py`** — configuration from environment variables.
- **`watcher.py`** — workspace filesystem watcher. Detects external changes
  and provides a `drain()` interface for injecting workspace pulse messages.
- **`testing.py`** — in-memory test doubles (`MemoryChat`, `MemoryVault`,
  `MemoryWatcher`, `MemoryBand`, etc.). Excluded from coverage. Used by
  plugin test suites.

## The protocol ABCs

`ChatClient`, `Vault`, and `CommandExecutor` are the contracts that plugins
implement. When modifying these, you're changing the interface for every plugin
that implements them. Check all implementers before changing a method signature.

`ToolContext` is the dataclass that gets passed to every tool function. It
carries the workspace path, `line` (the conversation context), `chat_room`
(the chat room to post to, empty for non-chat lines), and references to
chat/vault/executor. Tools declare what they need through their type hints.

## Testing

The `tests/` directory mirrors `src/` structure roughly. `tests/brain/` tests
the agentic loop, `tests/tools/` tests built-in tools, `tests/main/` tests
the startup and message handling paths.

The `conftest.py` at the test root provides:
- `_isolated_data_dir` (autouse) — patches `environment` paths to `tmp_path`
  so tests never touch the real filesystem
- `workspace` — a clean workspace directory
- `tool_context` — a `ToolContext` wired to the test workspace

Many tests here build a `Brain` with a fake backend. Look at existing tests
for the pattern — the backend protocol is simple enough to stub.
