"""Tests for lock acquisition, chat backend discovery, executor discovery, and docket tool registration."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.chat import discover_chat_backend
from docketeer.executor import discover_executor
from docketeer.main import (
    _acquire_lock,
    _load_task_collections,
    _register_docket_tools,
    _register_task_plugins,
    _task_collection_args,
)
from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext, registry
from docketeer.vault import discover_vault


def test_acquire_lock_success(tmp_path: Path):
    _acquire_lock(tmp_path)
    assert (tmp_path / "docketeer.lock").exists()


def test_acquire_lock_already_held(tmp_path: Path):
    import fcntl

    lock_path = tmp_path / "docketeer.lock"
    held = lock_path.open("w")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(SystemExit):
            _acquire_lock(tmp_path)
    finally:
        held.close()


def test_discover_chat_backend():
    client = MemoryChat()
    module = MagicMock()
    module.create_client.return_value = client

    ep = MagicMock()
    ep.load.return_value = module
    with patch("docketeer.chat.discover_one", return_value=ep):
        result_client, register_fn = discover_chat_backend()
    assert result_client is client
    assert register_fn is not None


def test_discover_chat_backend_no_register_tools():
    client = MemoryChat()
    module = SimpleNamespace(create_client=lambda: client)

    ep = MagicMock()
    ep.load.return_value = module
    with patch("docketeer.chat.discover_one", return_value=ep):
        result_client, register_fn = discover_chat_backend()
    assert result_client is client
    # Should get the noop default, not None
    assert callable(register_fn)
    register_fn(client, ToolContext(workspace=Path("/tmp")))  # should not raise


def test_discover_chat_backend_no_plugins():
    with patch("docketeer.chat.discover_one", return_value=None):
        with pytest.raises(RuntimeError, match="No chat backend installed"):
            discover_chat_backend()


def test_discover_executor_present():
    module = MagicMock()
    executor = MagicMock()
    module.create_executor.return_value = executor

    ep = MagicMock()
    ep.load.return_value = module
    with patch("docketeer.executor.discover_one", return_value=ep):
        result = discover_executor()
    assert result is executor


def test_discover_executor_absent():
    with patch("docketeer.executor.discover_one", return_value=None):
        result = discover_executor()
    assert result is None


def test_discover_vault_present():
    module = MagicMock()
    vault = MagicMock()
    module.create_vault.return_value = vault

    ep = MagicMock()
    ep.load.return_value = module
    with patch("docketeer.vault.discover_one", return_value=ep):
        result = discover_vault()
    assert result is vault


def test_discover_vault_absent():
    with patch("docketeer.vault.discover_one", return_value=None):
        result = discover_vault()
    assert result is None


async def test_register_docket_tools_schedule_with_key(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    _register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {
            "prompt": "remind chris",
            "when": "2026-12-25T10:00:00-05:00",
            "key": "xmas-reminder",
        },
        tool_context,
    )
    assert "xmas-reminder" in result
    mock_docket.replace.assert_called_once()


async def test_register_docket_tools_schedule_without_key(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    _register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {"prompt": "do thing", "when": "2026-12-25T10:00:00-05:00"},
        tool_context,
    )
    assert "task-" in result
    mock_docket.add.assert_called_once()


async def test_register_docket_tools_schedule_bad_datetime(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    _register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {"prompt": "test", "when": "not-a-date"},
        tool_context,
    )
    assert "invalid datetime" in result


async def test_register_docket_tools_schedule_silent(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    _register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {"prompt": "quiet", "when": "2026-12-25T10:00:00-05:00", "silent": True},
        tool_context,
    )
    assert "silently" in result


async def test_register_docket_tools_schedule_passes_thread_id(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    tool_context.thread_id = "parent_1"
    _register_docket_tools(mock_docket, tool_context)
    await registry.execute(
        "schedule",
        {
            "prompt": "reply in thread",
            "when": "2026-12-25T10:00:00-05:00",
            "key": "thread-task",
        },
        tool_context,
    )
    mock_docket.replace.assert_called_once()
    call_kwargs = mock_docket.replace.return_value.call_args[1]
    assert call_kwargs["thread_id"] == "parent_1"


async def test_register_docket_tools_schedule_no_thread_by_default(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    _register_docket_tools(mock_docket, tool_context)
    await registry.execute(
        "schedule",
        {"prompt": "do thing", "when": "2026-12-25T10:00:00-05:00", "key": "no-thread"},
        tool_context,
    )
    call_kwargs = mock_docket.replace.return_value.call_args[1]
    assert call_kwargs["thread_id"] == ""


async def test_register_docket_tools_cancel_task(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    _register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("cancel_task", {"key": "old-task"}, tool_context)
    assert "Cancelled" in result
    mock_docket.cancel.assert_called_once_with("old-task")


async def test_register_docket_tools_list_scheduled_empty(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    snapshot = MagicMock()
    snapshot.future = []
    snapshot.running = []
    mock_docket.snapshot.return_value = snapshot

    _register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert result == "No scheduled tasks"


async def test_register_docket_tools_list_scheduled_with_tasks(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    future_task = MagicMock()
    future_task.key = "task-1"
    future_task.when = datetime(2026, 12, 25, 10, 0, tzinfo=UTC)
    future_task.kwargs = {"prompt": "do thing"}

    running_task = MagicMock()
    running_task.key = "task-2"
    running_task.kwargs = {"prompt": "running now"}

    snapshot = MagicMock()
    snapshot.future = [future_task]
    snapshot.running = [running_task]
    mock_docket.snapshot.return_value = snapshot

    _register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert "2 task(s)" in result
    assert "task-1" in result
    assert "task-2" in result
    assert "RUNNING" in result


async def test_register_docket_tools_list_scheduled_long_prompt(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    task = MagicMock()
    task.key = "task-1"
    task.when = datetime(2026, 12, 25, 10, 0, tzinfo=UTC)
    task.kwargs = {"prompt": "x" * 100}

    snapshot = MagicMock()
    snapshot.future = [task]
    snapshot.running = []
    mock_docket.snapshot.return_value = snapshot

    _register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert "..." in result


async def test_register_docket_tools_list_scheduled_long_running_prompt(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    task = MagicMock()
    task.key = "task-r"
    task.kwargs = {"prompt": "y" * 100}

    snapshot = MagicMock()
    snapshot.future = []
    snapshot.running = [task]
    mock_docket.snapshot.return_value = snapshot

    _register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert "..." in result
    assert "RUNNING" in result


def test_load_task_collections_single_plugin():
    with patch(
        "docketeer.main.discover_all", return_value=[["docketeer_git:git_tasks"]]
    ):
        assert _load_task_collections() == ["docketeer_git:git_tasks"]


def test_load_task_collections_multiple_from_one_plugin():
    with patch(
        "docketeer.main.discover_all", return_value=[["pkg:tasks_a", "pkg:tasks_b"]]
    ):
        assert _load_task_collections() == ["pkg:tasks_a", "pkg:tasks_b"]


def test_load_task_collections_no_plugins():
    with patch("docketeer.main.discover_all", return_value=[]):
        assert _load_task_collections() == []


def test_register_task_plugins_registers_collections(mock_docket: MagicMock):
    with patch(
        "docketeer.main.discover_all", return_value=[["docketeer_git:git_tasks"]]
    ):
        _register_task_plugins(mock_docket)
    mock_docket.register_collection.assert_called_once_with("docketeer_git:git_tasks")


def test_register_task_plugins_no_plugins(mock_docket: MagicMock):
    with patch("docketeer.main.discover_all", return_value=[]):
        _register_task_plugins(mock_docket)
    mock_docket.register_collection.assert_not_called()


def test_task_collection_args_core_only():
    with patch("docketeer.main.discover_all", return_value=[]):
        args = _task_collection_args()
    assert args == ["--tasks", "docketeer.tasks:docketeer_tasks"]


def test_task_collection_args_with_plugins():
    with patch(
        "docketeer.main.discover_all", return_value=[["docketeer_git:git_tasks"]]
    ):
        args = _task_collection_args()
    assert args == [
        "--tasks",
        "docketeer.tasks:docketeer_tasks",
        "--tasks",
        "docketeer_git:git_tasks",
    ]
