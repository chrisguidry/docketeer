"""Tests for the vault tools."""

from pathlib import Path
from unittest.mock import AsyncMock, PropertyMock

import pytest

from docketeer.executor import CommandExecutor, RunningProcess
from docketeer.testing import MemoryVault
from docketeer.tools import ToolContext, registry


@pytest.fixture()
def vault() -> MemoryVault:
    return MemoryVault({"api-key": "sk-123", "db/password": "hunter2"})


@pytest.fixture()
def vault_context(workspace: Path, vault: MemoryVault) -> ToolContext:
    return ToolContext(workspace=workspace, room_id="room1", vault=vault)


# --- list_secrets ---


async def test_list_secrets(vault_context: ToolContext):
    result = await registry.execute("list_secrets", {}, vault_context)
    assert "api-key" in result
    assert "db/password" in result


async def test_list_secrets_empty():
    ctx = ToolContext(workspace=Path("/tmp"), vault=MemoryVault())
    result = await registry.execute("list_secrets", {}, ctx)
    assert "No secrets" in result


async def test_list_secrets_no_vault(tool_context: ToolContext):
    result = await registry.execute("list_secrets", {}, tool_context)
    assert "No vault" in result


# --- store_secret ---


async def test_store_secret(vault_context: ToolContext, vault: MemoryVault):
    result = await registry.execute(
        "store_secret", {"name": "new-key", "value": "val"}, vault_context
    )
    assert "Stored" in result
    assert await vault.resolve("new-key") == "val"


async def test_store_secret_no_vault(tool_context: ToolContext):
    result = await registry.execute(
        "store_secret", {"name": "x", "value": "y"}, tool_context
    )
    assert "No vault" in result


# --- generate_secret ---


async def test_generate_secret(vault_context: ToolContext, vault: MemoryVault):
    result = await registry.execute("generate_secret", {"name": "rand"}, vault_context)
    assert "Generated" in result
    assert "32" in result
    value = await vault.resolve("rand")
    assert len(value) == 32


async def test_generate_secret_custom_length(
    vault_context: ToolContext, vault: MemoryVault
):
    result = await registry.execute(
        "generate_secret", {"name": "short", "length": 16}, vault_context
    )
    assert "16" in result
    value = await vault.resolve("short")
    assert len(value) == 16


async def test_generate_secret_no_vault(tool_context: ToolContext):
    result = await registry.execute("generate_secret", {"name": "x"}, tool_context)
    assert "No vault" in result


# --- delete_secret ---


async def test_delete_secret(vault_context: ToolContext, vault: MemoryVault):
    result = await registry.execute("delete_secret", {"name": "api-key"}, vault_context)
    assert "Deleted" in result
    refs = await vault.list_secrets()
    names = {r.name for r in refs}
    assert "api-key" not in names


async def test_delete_secret_missing(vault_context: ToolContext):
    result = await registry.execute(
        "delete_secret", {"name": "nonexistent"}, vault_context
    )
    assert "Error" in result


async def test_delete_secret_no_vault(tool_context: ToolContext):
    result = await registry.execute("delete_secret", {"name": "x"}, tool_context)
    assert "No vault" in result


# --- capture_secret ---


@pytest.fixture()
def mock_executor(vault_context: ToolContext) -> AsyncMock:
    executor = AsyncMock(spec=CommandExecutor)
    proc = AsyncMock()
    proc.communicate.return_value = (b"captured-value\n", b"")
    type(proc).returncode = PropertyMock(return_value=0)
    executor.start.return_value = RunningProcess(proc)
    vault_context.executor = executor
    return executor


async def test_capture_secret(
    vault_context: ToolContext, vault: MemoryVault, mock_executor: AsyncMock
):
    result = await registry.execute(
        "capture_secret",
        {"name": "token", "command": "gh auth token"},
        vault_context,
    )
    assert "Captured" in result
    assert "token" in result
    assert "14" in result  # len("captured-value")
    assert await vault.resolve("token") == "captured-value"


async def test_capture_secret_strips_whitespace(
    vault_context: ToolContext, vault: MemoryVault, mock_executor: AsyncMock
):
    proc = mock_executor.start.return_value._process
    proc.communicate.return_value = (b"  spaced  \n", b"")

    await registry.execute(
        "capture_secret",
        {"name": "trimmed", "command": "echo spaced"},
        vault_context,
    )
    assert await vault.resolve("trimmed") == "spaced"


async def test_capture_secret_nonzero_exit(
    vault_context: ToolContext, mock_executor: AsyncMock
):
    proc = mock_executor.start.return_value._process
    proc.communicate.return_value = (b"", b"auth failed\n")
    type(proc).returncode = PropertyMock(return_value=1)

    result = await registry.execute(
        "capture_secret",
        {"name": "fail", "command": "bad-cmd"},
        vault_context,
    )
    assert "failed" in result.lower()
    assert "exit code 1" in result


async def test_capture_secret_no_executor(vault_context: ToolContext):
    vault_context.executor = None
    result = await registry.execute(
        "capture_secret",
        {"name": "x", "command": "echo hi"},
        vault_context,
    )
    assert "No executor" in result


async def test_capture_secret_no_vault(tool_context: ToolContext):
    result = await registry.execute(
        "capture_secret",
        {"name": "x", "command": "echo hi"},
        tool_context,
    )
    assert "No vault" in result


async def test_capture_secret_with_network(
    vault_context: ToolContext, vault: MemoryVault, mock_executor: AsyncMock
):
    await registry.execute(
        "capture_secret",
        {"name": "net", "command": "curl example.com", "network": True},
        vault_context,
    )
    assert mock_executor.start.call_args.kwargs["network_access"] is True
