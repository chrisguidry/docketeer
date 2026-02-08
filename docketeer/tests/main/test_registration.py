"""Tests for lock acquisition, chat backend discovery, and docket tool registration."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.main import (
    _acquire_lock,
    _discover_chat_backend,
    _load_task_collections,
    _register_docket_tools,
    _register_task_plugins,
    _task_collection_args,
)
from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext, registry


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
    with patch("importlib.metadata.entry_points", return_value=[ep]):
        result_client, register_fn = _discover_chat_backend()
    assert result_client is client
    assert register_fn is not None


def test_discover_chat_backend_no_register_tools():
    client = MemoryChat()
    module = SimpleNamespace(create_client=lambda: client)

    ep = MagicMock()
    ep.load.return_value = module
    with patch("importlib.metadata.entry_points", return_value=[ep]):
        result_client, register_fn = _discover_chat_backend()
    assert result_client is client
    assert register_fn is None


def test_discover_chat_backend_no_plugins():
    with patch("importlib.metadata.entry_points", return_value=[]):
        with pytest.raises(RuntimeError, match="No chat backend installed"):
            _discover_chat_backend()


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
    ep = MagicMock()
    ep.load.return_value = ["docketeer_git:git_tasks"]
    with patch("importlib.metadata.entry_points", return_value=[ep]):
        assert _load_task_collections() == ["docketeer_git:git_tasks"]


def test_load_task_collections_multiple_from_one_plugin():
    ep = MagicMock()
    ep.load.return_value = ["pkg:tasks_a", "pkg:tasks_b"]
    with patch("importlib.metadata.entry_points", return_value=[ep]):
        assert _load_task_collections() == ["pkg:tasks_a", "pkg:tasks_b"]


def test_load_task_collections_no_plugins():
    with patch("importlib.metadata.entry_points", return_value=[]):
        assert _load_task_collections() == []


def test_load_task_collections_handles_failure():
    ep = MagicMock()
    ep.name = "broken"
    ep.load.side_effect = ImportError("oops")
    with patch("importlib.metadata.entry_points", return_value=[ep]):
        assert _load_task_collections() == []


def test_register_task_plugins_registers_collections(mock_docket: MagicMock):
    ep = MagicMock()
    ep.load.return_value = ["docketeer_git:git_tasks"]
    with patch("importlib.metadata.entry_points", return_value=[ep]):
        _register_task_plugins(mock_docket)
    mock_docket.register_collection.assert_called_once_with("docketeer_git:git_tasks")


def test_register_task_plugins_no_plugins(mock_docket: MagicMock):
    with patch("importlib.metadata.entry_points", return_value=[]):
        _register_task_plugins(mock_docket)
    mock_docket.register_collection.assert_not_called()


def test_task_collection_args_core_only():
    with patch("importlib.metadata.entry_points", return_value=[]):
        args = _task_collection_args()
    assert args == ["--tasks", "docketeer.tasks:docketeer_tasks"]


def test_task_collection_args_with_plugins():
    ep = MagicMock()
    ep.load.return_value = ["docketeer_git:git_tasks"]
    with patch("importlib.metadata.entry_points", return_value=[ep]):
        args = _task_collection_args()
    assert args == [
        "--tasks",
        "docketeer.tasks:docketeer_tasks",
        "--tasks",
        "docketeer_git:git_tasks",
    ]
