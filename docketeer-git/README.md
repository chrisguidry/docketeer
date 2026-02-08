# docketeer-git

Git-backed workspace backup plugin for
[Docketeer](https://pypi.org/project/docketeer/). Automatically commits the
agent's workspace (`~/.docketeer/memory/`) to a local git repo on a timer, and
optionally pushes to a remote for off-machine backup.

Install `docketeer-git` alongside `docketeer` and backups start automatically.
No agent-facing tools are added — the agent doesn't know about backups.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DOCKETEER_GIT_BACKUP_INTERVAL` | `PT5M` | How often to check for changes (ISO 8601 duration or seconds) |
| `DOCKETEER_GIT_REMOTE` | _(empty)_ | Remote URL to push to. No push if unset. |
| `DOCKETEER_GIT_BRANCH` | `main` | Branch name to use |
| `DOCKETEER_GIT_AUTHOR_NAME` | `Docketeer` | Git author name for backup commits |
| `DOCKETEER_GIT_AUTHOR_EMAIL` | `docketeer@localhost` | Git author email for backup commits |

## How it works

A periodic docket task checks the workspace for uncommitted changes every 5
minutes (configurable). If anything changed, it stages everything and commits
with a timestamped message. If `DOCKETEER_GIT_REMOTE` is set, it pushes after
each commit. Push failures are logged but don't crash the agent.

The git repo is initialized automatically on first run. You can browse the
history with standard git tools (`git log`, `git diff`, etc.) in the workspace
directory.
