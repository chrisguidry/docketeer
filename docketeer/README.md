# Docketeer

The core agent engine for building autonomous AI assistants with
[Anthropic](https://platform.claude.com/docs/en/api/sdks/python) and
[Docket](https://github.com/chrisguidry/docket).

Docketeer is a small, opinionated toolkit for running an AI agent that can
manage its own memory, schedule its own future work, and extend itself through
plugins. The core package provides the agent loop, a persistent workspace for
the agent's files and journal, and a plugin system based on standard Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/).

## Tools

### Workspace

- **`list_files`** — list files and directories in the workspace
- **`read_file`** — read contents of a text file
- **`write_file`** — write content to a text file
- **`delete_file`** — delete a file
- **`search_files`** — search for text across files (case-insensitive)

### Journal

- **`journal_add`** — add a timestamped entry to today's journal
- **`journal_read`** — read journal entries for a day or date range
- **`journal_search`** — search across all journal entries

### Scheduling

- **`schedule`** — schedule a future nudge to prompt the agent at a given time
- **`cancel_task`** — cancel a scheduled task
- **`list_scheduled`** — list all scheduled and running tasks

## Configuration

| Variable                       | Default                    | Description                                  |
|--------------------------------|----------------------------|----------------------------------------------|
| `DOCKETEER_ANTHROPIC_API_KEY`  | _(required)_               | Anthropic API key                            |
| `DOCKETEER_CLAUDE_MODEL`       | `claude-opus-4-6`          | Claude model to use                          |
| `DOCKETEER_DATA_DIR`           | `~/.docketeer`             | Where the agent stores memory and audit logs |
| `DOCKETEER_DOCKET_URL`         | `redis://localhost:6379/0` | Redis connection for task scheduling         |
| `DOCKETEER_DOCKET_NAME`        | `docketeer`                | Name of the Docket instance                  |
| `DOCKETEER_REVERIE_INTERVAL`   | `PT30M` (30 min)           | Background thinking cycle interval           |
| `DOCKETEER_CONSOLIDATION_CRON` | `0 3 * * *`                | Cron schedule for daily memory consolidation |
| `DOCKETEER_CHAT`               | _(auto)_                   | Entry point name to select when multiple chat plugins are installed |
| `DOCKETEER_EXECUTOR`           | _(auto)_                   | Entry point name to select when multiple executor plugins are installed |

## Plugins

Docketeer discovers plugins through four entry point groups:

- **`docketeer.chat`** — chat backends (how the agent talks to people)
- **`docketeer.executor`** — command executors (sandboxed process execution)
- **`docketeer.tools`** — tool plugins (what the agent can do)
- **`docketeer.prompt`** — system prompt providers (contribute blocks to the system prompt)
- **`docketeer.tasks`** — background task plugins (periodic or scheduled work)

Available plugins:

- [docketeer-1password](https://pypi.org/project/docketeer-1password/) — 1Password secret vault
- [docketeer-agentskills](https://pypi.org/project/docketeer-agentskills/) — Agent Skills support
- [docketeer-bubblewrap](https://pypi.org/project/docketeer-bubblewrap/) — sandboxed command execution via bubblewrap
- [docketeer-git](https://pypi.org/project/docketeer-git/) — automatic git-backed workspace backups
- [docketeer-mcp](https://pypi.org/project/docketeer-mcp/) — MCP server support
- [docketeer-monty](https://pypi.org/project/docketeer-monty/) — sandboxed Python execution
- [docketeer-rocketchat](https://pypi.org/project/docketeer-rocketchat/) — Rocket Chat backend
- [docketeer-web](https://pypi.org/project/docketeer-web/) — web search, HTTP requests, file downloads
