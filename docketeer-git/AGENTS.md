# docketeer-git

Automatic git-backed workspace backups. Registers `docketeer.tasks` to
periodically commit the agent's workspace to a local git repo.

## Structure

- **`backup.py`** — the backup task. Initializes a git repo in the workspace
  if needed, stages all changes, and commits with a timestamp. Runs as a
  Docket periodic task.

## Testing

The `conftest.py` provides an isolated git repo fixture. Tests create files,
run the backup, and verify the resulting git history. All git operations
happen in `tmp_path`.
