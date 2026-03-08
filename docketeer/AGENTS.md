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
- **`vault.py`** — the `Vault` ABC. Vault plugins (1password) implement this.
- **`executor.py`** — the `CommandExecutor` ABC. Executor plugins (bubblewrap)
  implement this.
- **`tools/`** — built-in tool implementations (workspace files, vault,
  executor). The `__init__.py` has the tool registry and `ToolContext`.
- **`plugins.py`** — entry point discovery. `discover_one()` for single-select
  plugins, `discover_all()` for multi-load.
- **`prompt.py`** — system prompt assembly from prompt providers.
- **`tasks.py`** — Docket task definitions (nudge).
- **`handlers.py`** — message handling and the bridge between chat and brain.
- **`antenna.py`** — the realtime event feed system. Defines the `Band` ABC,
  `Signal`, `SignalFilter`, `Tuning` data types, filter evaluation, and
  tuning persistence. Band plugins (wicket, atproto) implement the `Band` ABC.
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
