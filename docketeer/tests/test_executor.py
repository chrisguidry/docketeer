"""Tests for the CommandExecutor ABC and supporting dataclasses."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from docketeer.executor import CommandExecutor, CompletedProcess, Mount, RunningProcess


def test_mount_defaults():
    m = Mount(source=Path("/src"), target=Path("/dst"))
    assert m.source == Path("/src")
    assert m.target == Path("/dst")
    assert m.writable is False


def test_mount_writable():
    m = Mount(source=Path("/a"), target=Path("/b"), writable=True)
    assert m.writable is True


def test_completed_process():
    cp = CompletedProcess(returncode=0, stdout=b"out", stderr=b"err")
    assert cp.returncode == 0
    assert cp.stdout == b"out"
    assert cp.stderr == b"err"


def test_running_process_pid():
    proc = MagicMock()
    proc.pid = 42
    rp = RunningProcess(proc)
    assert rp.pid == 42


def test_running_process_stdin():
    proc = MagicMock()
    proc.stdin = "fake_stdin"
    rp = RunningProcess(proc)
    assert rp.stdin == "fake_stdin"


def test_running_process_stdout():
    proc = MagicMock()
    proc.stdout = "fake_stdout"
    rp = RunningProcess(proc)
    assert rp.stdout == "fake_stdout"


def test_running_process_stderr():
    proc = MagicMock()
    proc.stderr = "fake_stderr"
    rp = RunningProcess(proc)
    assert rp.stderr == "fake_stderr"


def test_running_process_returncode():
    proc = MagicMock()
    type(proc).returncode = PropertyMock(return_value=0)
    rp = RunningProcess(proc)
    assert rp.returncode == 0


def test_running_process_returncode_none():
    proc = MagicMock()
    type(proc).returncode = PropertyMock(return_value=None)
    rp = RunningProcess(proc)
    assert rp.returncode is None


async def test_running_process_wait():
    proc = AsyncMock()
    proc.communicate.return_value = (b"stdout", b"stderr")
    type(proc).returncode = PropertyMock(return_value=0)
    rp = RunningProcess(proc)
    result = await rp.wait()
    assert isinstance(result, CompletedProcess)
    assert result.returncode == 0
    assert result.stdout == b"stdout"
    assert result.stderr == b"stderr"


def test_running_process_terminate():
    proc = MagicMock()
    rp = RunningProcess(proc)
    rp.terminate()
    proc.terminate.assert_called_once()


def test_running_process_terminate_already_exited():
    proc = MagicMock()
    proc.terminate.side_effect = ProcessLookupError
    rp = RunningProcess(proc)
    rp.terminate()


def test_running_process_kill():
    proc = MagicMock()
    rp = RunningProcess(proc)
    rp.kill()
    proc.kill.assert_called_once()


def test_running_process_kill_already_exited():
    proc = MagicMock()
    proc.kill.side_effect = ProcessLookupError
    rp = RunningProcess(proc)
    rp.kill()


def test_command_executor_cannot_be_instantiated():
    with pytest.raises(TypeError):
        CommandExecutor()
