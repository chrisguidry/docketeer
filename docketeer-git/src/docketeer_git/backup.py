"""Git-backed workspace backup — periodic commit and optional push."""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from docket.dependencies import Perpetual, Timeout

from docketeer import environment
from docketeer.brain.backend import InferenceBackend
from docketeer.dependencies import (
    CurrentInferenceBackend,
    EnvironmentStr,
    WorkspacePath,
)

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


@dataclass
class GitResult:
    """Captured output from a git subprocess."""

    returncode: int
    stdout: bytes
    stderr: bytes


async def _git(
    cwd: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> GitResult:
    """Run a git command and return the captured result."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **env} if env else None,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode is not None
    return GitResult(returncode=proc.returncode, stdout=stdout, stderr=stderr)


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
    result = await _git(workspace, "status", "--porcelain")
    return bool(result.stdout.strip())


async def _generate_commit_message(
    backend: InferenceBackend | None,
    diff: str,
) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    if not backend or not diff.strip():
        return f"backup: {timestamp}"
    try:
        truncated = diff[:10_000]
        summary = await backend.utility_complete(
            "Summarize these workspace changes in one sentence for a git "
            "commit message. No quotes, no prefix, just the message.\n\n"
            f"{truncated}",
            max_tokens=128,
        )
        return summary.strip() or f"backup: {timestamp}"
    except Exception:
        log.debug("LLM commit message failed, using timestamp", exc_info=True)
        return f"backup: {timestamp}"


async def backup(
    perpetual: Perpetual = Perpetual(every=BACKUP_INTERVAL, automatic=True),
    timeout: Timeout = Timeout(timedelta(seconds=60)),
    workspace: Path = WorkspacePath(),
    remote: str = EnvironmentStr("GIT_REMOTE", ""),
    branch: str = EnvironmentStr("GIT_BRANCH", "main"),
    author_name: str = EnvironmentStr("GIT_AUTHOR_NAME", "Docketeer"),
    author_email: str = EnvironmentStr("GIT_AUTHOR_EMAIL", "docketeer@localhost"),
    backend: InferenceBackend | None = CurrentInferenceBackend(),
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

    has_changes = await _has_changes(workspace)
    if not has_changes:
        return

    await _git(workspace, "add", ".")

    diff_result = await _git(workspace, "diff", "--cached")
    diff_text = diff_result.stdout.decode()

    message = await _generate_commit_message(backend, diff_text)

    author_env = {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
    }

    await _git(workspace, "commit", "-m", message, env=author_env)
    log.info("Workspace backup committed: %s", message)

    if remote:
        result = await _git(workspace, "push", "-u", "origin", branch)
        if result.returncode != 0:
            log.warning("Push failed: %s", result.stderr.decode())
