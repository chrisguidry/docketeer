"""Tests for the run and shell tools."""

from pathlib import Path
from unittest.mock import AsyncMock, PropertyMock

import pytest

from docketeer.executor import CommandExecutor, RunningProcess
from docketeer.testing import MemoryVault
from docketeer.tools import ToolContext, registry


@pytest.fixture()
def mock_executor(tool_context: ToolContext) -> AsyncMock:
    executor = AsyncMock(spec=CommandExecutor)
    proc = AsyncMock()
    proc.communicate.return_value = (b"", b"")
    type(proc).returncode = PropertyMock(return_value=0)
    executor.start.return_value = RunningProcess(proc)
    tool_context.executor = executor
    return executor


# --- run ---


async def test_run_no_executor(tool_context: ToolContext):
    tool_context.executor = None
    result = await registry.execute("run", {"args": ["echo", "hi"]}, tool_context)
    assert "No executor" in result


async def test_run_success(tool_context: ToolContext, mock_executor: AsyncMock):
    proc = mock_executor.start.return_value._process
    proc.communicate.return_value = (b"hello\n", b"")

    result = await registry.execute("run", {"args": ["echo", "hello"]}, tool_context)
    assert "hello" in result
    mock_executor.start.assert_called_once()
    assert mock_executor.start.call_args.args[0] == ["echo", "hello"]


async def test_run_nonzero_exit(tool_context: ToolContext, mock_executor: AsyncMock):
    proc = mock_executor.start.return_value._process
    proc.communicate.return_value = (b"", b"not found\n")
    type(proc).returncode = PropertyMock(return_value=127)

    result = await registry.execute("run", {"args": ["badcmd"]}, tool_context)
    assert "exit code 127" in result
    assert "not found" in result


async def test_run_with_network(tool_context: ToolContext, mock_executor: AsyncMock):
    await registry.execute(
        "run", {"args": ["curl", "example.com"], "network": True}, tool_context
    )
    assert mock_executor.start.call_args.kwargs["network_access"] is True


async def test_run_mounts(tool_context: ToolContext, mock_executor: AsyncMock):
    await registry.execute("run", {"args": ["ls", "/workspace"]}, tool_context)
    mounts = mock_executor.start.call_args.kwargs["mounts"]
    assert len(mounts) == 2

    assert mounts[0].target == Path("/workspace")
    assert mounts[0].source == tool_context.workspace
    assert mounts[0].writable is False

    assert mounts[1].target == Path("/tmp")
    assert mounts[1].source == tool_context.workspace / "tmp"
    assert mounts[1].writable is True


async def test_run_creates_scratch_dir(
    tool_context: ToolContext, mock_executor: AsyncMock
):
    scratch = tool_context.workspace / "tmp"
    assert not scratch.exists()
    await registry.execute("run", {"args": ["true"]}, tool_context)
    assert scratch.is_dir()


async def test_run_passes_agent_username(
    tool_context: ToolContext, mock_executor: AsyncMock
):
    tool_context.agent_username = "nix"
    await registry.execute("run", {"args": ["whoami"]}, tool_context)
    assert mock_executor.start.call_args.kwargs["username"] == "nix"


async def test_run_no_username_when_agent_username_unset(
    tool_context: ToolContext, mock_executor: AsyncMock
):
    await registry.execute("run", {"args": ["whoami"]}, tool_context)
    assert mock_executor.start.call_args.kwargs["username"] is None


# --- shell ---


async def test_shell_no_executor(tool_context: ToolContext):
    tool_context.executor = None
    result = await registry.execute("shell", {"command": "echo hi"}, tool_context)
    assert "No executor" in result


async def test_shell_wraps_in_sh(tool_context: ToolContext, mock_executor: AsyncMock):
    proc = mock_executor.start.return_value._process
    proc.communicate.return_value = (b"hello\n", b"")

    result = await registry.execute("shell", {"command": "echo hello"}, tool_context)
    assert "hello" in result
    assert mock_executor.start.call_args.args[0] == ["sh", "-c", "echo hello"]


async def test_shell_nonzero_exit(tool_context: ToolContext, mock_executor: AsyncMock):
    proc = mock_executor.start.return_value._process
    proc.communicate.return_value = (b"", b"error\n")
    type(proc).returncode = PropertyMock(return_value=1)

    result = await registry.execute("shell", {"command": "false"}, tool_context)
    assert "exit code 1" in result
    assert "error" in result


async def test_shell_with_network(tool_context: ToolContext, mock_executor: AsyncMock):
    await registry.execute(
        "shell", {"command": "curl example.com", "network": True}, tool_context
    )
    assert mock_executor.start.call_args.kwargs["network_access"] is True


async def test_shell_mounts(tool_context: ToolContext, mock_executor: AsyncMock):
    await registry.execute("shell", {"command": "ls /workspace"}, tool_context)
    mounts = mock_executor.start.call_args.kwargs["mounts"]
    assert len(mounts) == 2

    assert mounts[0].target == Path("/workspace")
    assert mounts[1].target == Path("/tmp")


async def test_shell_passes_agent_username(
    tool_context: ToolContext, mock_executor: AsyncMock
):
    tool_context.agent_username = "nix"
    await registry.execute("shell", {"command": "whoami"}, tool_context)
    assert mock_executor.start.call_args.kwargs["username"] == "nix"


# --- env ---


@pytest.fixture()
def vault_executor_context(
    tool_context: ToolContext, mock_executor: AsyncMock
) -> tuple[ToolContext, MemoryVault]:
    vault = MemoryVault({"api-key": "sk-123", "db/pass": "hunter2"})
    tool_context.vault = vault
    return tool_context, vault


async def test_run_env_resolves_secrets(
    vault_executor_context: tuple[ToolContext, MemoryVault],
    mock_executor: AsyncMock,
):
    ctx, _ = vault_executor_context
    await registry.execute(
        "run",
        {"args": ["curl"], "env": {"API_KEY": {"secret": "api-key"}}},
        ctx,
    )
    env = mock_executor.start.call_args.kwargs["env"]
    assert env == {"API_KEY": "sk-123"}


async def test_run_env_plain_strings(
    vault_executor_context: tuple[ToolContext, MemoryVault],
    mock_executor: AsyncMock,
):
    ctx, _ = vault_executor_context
    await registry.execute(
        "run",
        {"args": ["app"], "env": {"TZ": "UTC"}},
        ctx,
    )
    env = mock_executor.start.call_args.kwargs["env"]
    assert env == {"TZ": "UTC"}


async def test_run_env_mixed(
    vault_executor_context: tuple[ToolContext, MemoryVault],
    mock_executor: AsyncMock,
):
    ctx, _ = vault_executor_context
    await registry.execute(
        "run",
        {
            "args": ["app"],
            "env": {"TZ": "UTC", "API_KEY": {"secret": "api-key"}},
        },
        ctx,
    )
    env = mock_executor.start.call_args.kwargs["env"]
    assert env == {"TZ": "UTC", "API_KEY": "sk-123"}


async def test_run_env_missing_secret(
    vault_executor_context: tuple[ToolContext, MemoryVault],
):
    ctx, _ = vault_executor_context
    result = await registry.execute(
        "run",
        {"args": ["app"], "env": {"KEY": {"secret": "nonexistent"}}},
        ctx,
    )
    assert "Could not resolve secret 'nonexistent'" in result


async def test_run_env_secrets_no_vault(
    tool_context: ToolContext, mock_executor: AsyncMock
):
    result = await registry.execute(
        "run",
        {"args": ["app"], "env": {"KEY": {"secret": "val"}}},
        tool_context,
    )
    assert "No vault" in result


async def test_run_without_env_passes_none(
    tool_context: ToolContext, mock_executor: AsyncMock
):
    await registry.execute("run", {"args": ["true"]}, tool_context)
    assert mock_executor.start.call_args.kwargs.get("env") is None


async def test_shell_env_resolves_secrets(
    vault_executor_context: tuple[ToolContext, MemoryVault],
    mock_executor: AsyncMock,
):
    ctx, _ = vault_executor_context
    await registry.execute(
        "shell",
        {"command": "echo $API_KEY", "env": {"API_KEY": {"secret": "api-key"}}},
        ctx,
    )
    env = mock_executor.start.call_args.kwargs["env"]
    assert env == {"API_KEY": "sk-123"}


async def test_shell_env_missing_secret(
    vault_executor_context: tuple[ToolContext, MemoryVault],
):
    ctx, _ = vault_executor_context
    result = await registry.execute(
        "shell",
        {"command": "echo", "env": {"KEY": {"secret": "nonexistent"}}},
        ctx,
    )
    assert "Could not resolve secret 'nonexistent'" in result


async def test_shell_env_secrets_no_vault(
    tool_context: ToolContext, mock_executor: AsyncMock
):
    result = await registry.execute(
        "shell",
        {"command": "echo", "env": {"KEY": {"secret": "val"}}},
        tool_context,
    )
    assert "No vault" in result


async def test_shell_without_env_passes_none(
    tool_context: ToolContext, mock_executor: AsyncMock
):
    await registry.execute("shell", {"command": "true"}, tool_context)
    assert mock_executor.start.call_args.kwargs.get("env") is None
