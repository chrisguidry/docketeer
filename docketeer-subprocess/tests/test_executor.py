"""Tests for the subprocess executor."""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.executor import Mount
from docketeer_subprocess import SubprocessExecutor, create_executor


def test_create_executor():
    executor = create_executor()
    assert isinstance(executor, SubprocessExecutor)


@pytest.fixture()
def mock_process() -> AsyncMock:
    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.pid = 42
    proc.stdin = AsyncMock()
    proc.stdout = AsyncMock()
    proc.stderr = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"out", b"err"))
    return proc


# --- start() ---


async def test_start_runs_command(mock_process: AsyncMock):
    executor = SubprocessExecutor()
    with patch("docketeer_subprocess.executor.asyncio") as mock_asyncio:
        mock_asyncio.subprocess = asyncio.subprocess
        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_process)

        rp = await executor.start(["echo", "hello"])

    mock_asyncio.create_subprocess_exec.assert_called_once()
    call_args = mock_asyncio.create_subprocess_exec.call_args
    assert call_args[0] == ("echo", "hello")
    assert rp.pid == 42


async def test_start_merges_env(mock_process: AsyncMock):
    executor = SubprocessExecutor()
    with patch("docketeer_subprocess.executor.asyncio") as mock_asyncio:
        mock_asyncio.subprocess = asyncio.subprocess
        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_process)

        await executor.start(["env"], env={"MY_VAR": "test_value"})

    call_kwargs = mock_asyncio.create_subprocess_exec.call_args[1]
    assert call_kwargs["env"]["MY_VAR"] == "test_value"
    assert "PATH" in call_kwargs["env"]


async def test_start_uses_first_mount_as_cwd(mock_process: AsyncMock, tmp_path: Path):
    executor = SubprocessExecutor()
    mounts = [
        Mount(source=tmp_path, target=Path("/workspace"), writable=True),
        Mount(source=Path("/other"), target=Path("/mnt/other")),
    ]
    with patch("docketeer_subprocess.executor.asyncio") as mock_asyncio:
        mock_asyncio.subprocess = asyncio.subprocess
        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_process)

        await executor.start(["ls"], mounts=mounts)

    call_kwargs = mock_asyncio.create_subprocess_exec.call_args[1]
    assert call_kwargs["cwd"] == tmp_path


async def test_start_sets_mount_env_vars(mock_process: AsyncMock, tmp_path: Path):
    executor = SubprocessExecutor()
    mounts = [
        Mount(source=tmp_path, target=Path("/workspace")),
        Mount(source=tmp_path / "scratch", target=Path("/tmp"), writable=True),
    ]
    with patch("docketeer_subprocess.executor.asyncio") as mock_asyncio:
        mock_asyncio.subprocess = asyncio.subprocess
        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_process)

        await executor.start(["ls"], mounts=mounts)

    call_kwargs = mock_asyncio.create_subprocess_exec.call_args[1]
    assert call_kwargs["env"]["WORKSPACE"] == str(tmp_path)
    assert call_kwargs["env"]["TMP"] == str(tmp_path / "scratch")


async def test_start_no_cwd_without_mounts(mock_process: AsyncMock):
    executor = SubprocessExecutor()
    with patch("docketeer_subprocess.executor.asyncio") as mock_asyncio:
        mock_asyncio.subprocess = asyncio.subprocess
        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_process)

        await executor.start(["ls"])

    call_kwargs = mock_asyncio.create_subprocess_exec.call_args[1]
    assert call_kwargs["cwd"] is None


async def test_start_ignores_network_and_username(mock_process: AsyncMock):
    executor = SubprocessExecutor()
    with patch("docketeer_subprocess.executor.asyncio") as mock_asyncio:
        mock_asyncio.subprocess = asyncio.subprocess
        mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_process)

        rp = await executor.start(
            ["echo", "hi"],
            network_access=True,
            username="someone",
        )

    result = await rp.wait()
    assert result.returncode == 0


async def test_start_env_overrides_inherited(mock_process: AsyncMock):
    executor = SubprocessExecutor()
    with patch.dict(os.environ, {"PATH": "/original"}):
        with patch("docketeer_subprocess.executor.asyncio") as mock_asyncio:
            mock_asyncio.subprocess = asyncio.subprocess
            mock_asyncio.create_subprocess_exec = AsyncMock(return_value=mock_process)

            await executor.start(["ls"], env={"PATH": "/custom"})

    call_kwargs = mock_asyncio.create_subprocess_exec.call_args[1]
    assert call_kwargs["env"]["PATH"] == "/custom"
