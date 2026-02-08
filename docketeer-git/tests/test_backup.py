"""Tests for the git-backed workspace backup task."""

import subprocess
from pathlib import Path

import pytest

from docketeer_git.backup import _git, _git_config, backup


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


def git_log(workspace: Path) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--oneline", "--format=%s"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()


def git_branch(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


async def _backup(
    workspace: Path,
    *,
    remote: str = "",
    branch: str = "main",
    author_name: str = "Test",
    author_email: str = "test@test",
) -> None:
    """Call backup() with all dependency parameters resolved for tests."""
    await backup(
        workspace=workspace,
        remote=remote,
        branch=branch,
        author_name=author_name,
        author_email=author_email,
    )


async def test_initializes_repo(workspace: Path):
    (workspace / "test.txt").write_text("hello")
    await _backup(workspace)
    assert (workspace / ".git").is_dir()


async def test_uses_configured_branch(workspace: Path):
    (workspace / "test.txt").write_text("hello")
    await _backup(workspace, branch="backups")
    assert git_branch(workspace) == "backups"


async def test_commits_changes(workspace: Path):
    (workspace / "note.md").write_text("first")
    await _backup(workspace)
    commits = git_log(workspace)
    assert len(commits) == 1
    assert commits[0].startswith("backup: ")


async def test_clean_workspace_no_commit(workspace: Path):
    (workspace / "note.md").write_text("first")
    await _backup(workspace)
    await _backup(workspace)
    commits = git_log(workspace)
    assert len(commits) == 1


async def test_multiple_changes(workspace: Path):
    (workspace / "a.txt").write_text("one")
    await _backup(workspace)
    (workspace / "b.txt").write_text("two")
    await _backup(workspace)
    commits = git_log(workspace)
    assert len(commits) == 2


async def test_pushes_when_remote_configured(workspace: Path):
    remote = workspace.parent / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )

    (workspace / "note.md").write_text("push me")
    await _backup(workspace, remote=str(remote))

    result = subprocess.run(
        ["git", "log", "--oneline", "--format=%s"],
        cwd=remote,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "backup: " in result.stdout


async def test_no_push_without_remote(workspace: Path):
    (workspace / "note.md").write_text("no push")
    await _backup(workspace)
    assert (workspace / ".git").is_dir()
    result = subprocess.run(
        ["git", "remote"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""


async def test_push_failure_logged_not_raised(
    workspace: Path, caplog: pytest.LogCaptureFixture
):
    (workspace / "note.md").write_text("will fail push")
    await _backup(workspace, remote="https://invalid.example.com/nope.git")

    assert any("push failed" in r.message.lower() for r in caplog.records)


async def test_gitignore_created(workspace: Path):
    (workspace / "note.md").write_text("hello")
    await _backup(workspace)
    gitignore = workspace / ".gitignore"
    assert gitignore.exists()
    content = gitignore.read_text()
    assert "*.lock" in content
    assert "*.tmp" in content


async def test_gitignore_not_overwritten(workspace: Path):
    gitignore = workspace / ".gitignore"
    gitignore.write_text("custom\n")
    (workspace / "note.md").write_text("hello")
    await _backup(workspace)
    assert gitignore.read_text() == "custom\n"


async def test_sets_author_config(workspace: Path):
    (workspace / "note.md").write_text("hello")
    await _backup(workspace, author_name="Nix", author_email="nix@example.com")

    result = subprocess.run(
        ["git", "log", "--format=%an <%ae>", "-1"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "Nix <nix@example.com>"


async def test_git_helper(tmp_path: Path):
    result = await _git(tmp_path, "init")
    assert result.returncode == 0


async def test_git_config_helper(tmp_path: Path):
    await _git(tmp_path, "init")
    await _git_config(tmp_path, "user.name", "test")
    result = subprocess.run(
        ["git", "config", "user.name"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "test"


def test_git_tasks_exported():
    from docketeer_git import git_tasks

    assert backup in git_tasks


def test_task_collections_exported():
    from docketeer_git import task_collections

    assert "docketeer_git:git_tasks" in task_collections


async def test_empty_workspace_no_commit(workspace: Path):
    await _backup(workspace)
    assert not (workspace / ".git").is_dir()
