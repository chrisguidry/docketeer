"""Tests for lock acquisition, chat tool registration, and docket tool registration."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from docketeer.main import (
    _acquire_lock,
    _register_chat_tools,
    _register_docket_tools,
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


async def test_register_chat_tools_send_file(
    chat: MemoryChat, tool_context: ToolContext
):
    (tool_context.workspace / "test.txt").write_text("hello")
    _register_chat_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "test.txt"}, tool_context)
    assert "Sent" in result
    assert len(chat.uploaded_files) == 1


async def test_register_chat_tools_send_file_not_found(
    chat: MemoryChat, tool_context: ToolContext
):
    _register_chat_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "nope.txt"}, tool_context)
    assert "File not found" in result


async def test_register_chat_tools_send_file_is_dir(
    chat: MemoryChat, tool_context: ToolContext
):
    (tool_context.workspace / "subdir").mkdir()
    _register_chat_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "subdir"}, tool_context)
    assert "Cannot send a directory" in result


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
