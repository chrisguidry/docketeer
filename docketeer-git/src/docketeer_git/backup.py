"""Git-backed workspace backup — periodic commit and optional push."""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from docket.dependencies import Perpetual

from docketeer import environment
from docketeer.dependencies import EnvironmentStr, WorkspacePath

log = logging.getLogger(__name__)

BACKUP_INTERVAL = environment.get_timedelta("GIT_BACKUP_INTERVAL", timedelta(minutes=5))

DEFAULT_GITIGNORE = """\
*.lock
*.tmp
*.swp
*~
__pycache__/
tmp/
"""


async def _git(
    cwd: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> asyncio.subprocess.Process:
    """Run a git command and return the completed process."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **env} if env else None,
    )
    await proc.wait()
    return proc


async def _git_config(cwd: Path, key: str, value: str) -> None:
    await _git(cwd, "config", key, value)


async def _init_repo(
    workspace: Path,
    *,
    branch: str,
    remote: str,
    author_name: str,
    author_email: str,
) -> None:
    """Initialize a git repo in the workspace if one doesn't exist."""
    await _git(workspace, "init", "-b", branch)
    await _git_config(workspace, "user.name", author_name)
    await _git_config(workspace, "user.email", author_email)

    if remote:
        await _git(workspace, "remote", "add", "origin", remote)

    gitignore = workspace / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(DEFAULT_GITIGNORE)


async def _has_changes(workspace: Path) -> bool:
    """Check if the workspace has any uncommitted changes or untracked files."""
    status = await _git(workspace, "status", "--porcelain")
    assert status.stdout is not None
    output = await status.stdout.read()
    return bool(output.strip())


async def backup(
    perpetual: Perpetual = Perpetual(every=BACKUP_INTERVAL, automatic=True),
    workspace: Path = WorkspacePath(),
    remote: str = EnvironmentStr("GIT_REMOTE", ""),
    branch: str = EnvironmentStr("GIT_BRANCH", "main"),
    author_name: str = EnvironmentStr("GIT_AUTHOR_NAME", "Docketeer"),
    author_email: str = EnvironmentStr("GIT_AUTHOR_EMAIL", "docketeer@localhost"),
) -> None:
    """Commit workspace changes and optionally push to a remote."""
    if not any(workspace.iterdir()):
        return

    if not (workspace / ".git").is_dir():
        await _init_repo(
            workspace,
            branch=branch,
            remote=remote,
            author_name=author_name,
            author_email=author_email,
        )

    if not await _has_changes(workspace):
        return

    await _git(workspace, "add", ".")

    author_env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
    }

    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    await _git(workspace, "commit", "-m", f"backup: {timestamp}", env=author_env)
    log.info("Workspace backup committed: %s", timestamp)

    if remote:
        result = await _git(workspace, "push", "-u", "origin", branch)
        if result.returncode != 0:
            assert result.stderr is not None
            stderr = (await result.stderr.read()).decode()
            log.warning("Push failed: %s", stderr)
