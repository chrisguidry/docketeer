# Docketeer

The core agent engine for building autonomous AI assistants with
[Docket](https://github.com/chrisguidry/docket).

Docketeer is a small, opinionated toolkit for running an AI agent that can
manage its own memory, schedule its own future work, and extend itself through
plugins. The inference backend is pluggable — bring your own LLM provider. The
core package provides the agent loop, a persistent workspace for the agent's
files, and a plugin system based on standard Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/).

## Tools

### Workspace

- **`list_files`** — list files and directories in the workspace
- **`read_file`** — read contents of a text file
- **`write_file`** — write content to a text file
- **`edit_file`** — search-and-replace editing within a file
- **`delete_file`** — delete a file
- **`create_link`** — create a symbolic link in the workspace
- **`read_link`** — read the target of a symbolic link
- **`search_files`** — semantic search across workspace files (falls back to keyword grep without docketeer-search)

### Scheduling

- **`schedule`** — schedule a future nudge to prompt the agent at a given time
- **`schedule_every`** — schedule a recurring nudge on an interval
- **`cancel_task`** — cancel a scheduled task
- **`list_scheduled`** — list all scheduled and running tasks

### Chat

- **`list_rooms`** — list available chat rooms
- **`room_messages`** — read recent messages from a room
- **`send_message`** — send a message to a room
- **`react`** — react to a message with an emoji
- **`wrap_up_silently`** — end a turn without replying

### Vault

- **`list_secrets`** — list stored secret names
- **`store_secret`** — store a secret by name
- **`generate_secret`** — generate and store a random secret
- **`delete_secret`** — delete a stored secret
- **`capture_secret`** — capture a secret from command output

### Executor

- **`run`** — run a command in the sandbox
- **`shell`** — run a shell command in the sandbox

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOCKETEER_DATA_DIR` | `~/.docketeer` | Where the agent stores memory and audit logs |
| `DOCKETEER_DOCKET_URL` | `redis://localhost:6379/0` | Redis connection for task scheduling |
| `DOCKETEER_DOCKET_NAME` | `docketeer` | Name of the Docket instance |
| `DOCKETEER_CHAT_MODEL` | `balanced` | Model tier for chat conversations |
| `DOCKETEER_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `DOCKETEER_CHAT` | _(auto)_ | Entry point name to select when multiple chat plugins are installed |
| `DOCKETEER_INFERENCE` | _(auto)_ | Entry point name to select when multiple inference plugins are installed |
| `DOCKETEER_EXECUTOR` | _(auto)_ | Entry point name to select when multiple executor plugins are installed |
| `DOCKETEER_VAULT` | _(auto)_ | Entry point name to select when multiple vault plugins are installed |
| `DOCKETEER_SEARCH` | _(auto)_ | Entry point name to select when multiple search plugins are installed |

## Plugins

Docketeer discovers plugins through these entry point groups:

- **`docketeer.inference`** — inference backends (which LLM provider powers the agent)
- **`docketeer.chat`** — chat backends (how the agent talks to people)
- **`docketeer.executor`** — command executors (sandboxed process execution)
- **`docketeer.vault`** — secret vaults (store and resolve secrets)
- **`docketeer.search`** — search catalogs (semantic search over workspace and tools)
- **`docketeer.tools`** — tool plugins (what the agent can do)
- **`docketeer.prompt`** — system prompt providers (contribute blocks to the system prompt)
- **`docketeer.tasks`** — background task plugins (periodic or scheduled work)

Available plugins:

- [docketeer-1password](https://pypi.org/project/docketeer-1password/) — 1Password secret vault
- [docketeer-agentskills](https://pypi.org/project/docketeer-agentskills/) — Agent Skills support
- [docketeer-anthropic](https://pypi.org/project/docketeer-anthropic/) — Anthropic inference backend
- [docketeer-autonomy](https://pypi.org/project/docketeer-autonomy/) — autonomous inner life (reverie, consolidation, journaling, profiles)
- [docketeer-bubblewrap](https://pypi.org/project/docketeer-bubblewrap/) — sandboxed command execution via bubblewrap
- [docketeer-deepinfra](https://pypi.org/project/docketeer-deepinfra/) — DeepInfra inference backend
- [docketeer-git](https://pypi.org/project/docketeer-git/) — automatic git-backed workspace backups
- [docketeer-mcp](https://pypi.org/project/docketeer-mcp/) — MCP server support
- [docketeer-monty](https://pypi.org/project/docketeer-monty/) — sandboxed Python execution
- [docketeer-rocketchat](https://pypi.org/project/docketeer-rocketchat/) — Rocket.Chat backend
- [docketeer-search](https://pypi.org/project/docketeer-search/) — semantic workspace search via fastembed
- [docketeer-subprocess](https://pypi.org/project/docketeer-subprocess/) — unsandboxed command execution for containers and non-Linux hosts
- [docketeer-tui](https://pypi.org/project/docketeer-tui/) — terminal chat backend
- [docketeer-web](https://pypi.org/project/docketeer-web/) — web search, HTTP requests, file downloads
