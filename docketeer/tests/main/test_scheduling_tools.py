"""Tests for docket scheduling tools (schedule, schedule_every, list_scheduled, cancel)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from docket.dependencies import Perpetual

from docketeer.scheduling import _reserved_task_keys, register_docket_tools
from docketeer.tools import ToolContext, registry

# --- reserved key detection ---


def test_reserved_task_keys_skips_non_automatic():
    async def manual_task(  # pragma: no cover
        perpetual: Perpetual = Perpetual(),
    ) -> None: ...

    docket = MagicMock()
    docket.tasks = {"manual_task": manual_task}
    assert _reserved_task_keys(docket) == set()


# --- schedule tests ---


async def test_schedule_with_key(mock_docket: AsyncMock, tool_context: ToolContext):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {
            "prompt_file": "tasks/remind-chris.md",
            "when": "2026-12-25T10:00:00-05:00",
            "key": "xmas-reminder",
        },
        tool_context,
    )
    assert "xmas-reminder" in result
    mock_docket.replace.assert_called_once()


async def test_schedule_without_key(mock_docket: AsyncMock, tool_context: ToolContext):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {"prompt_file": "tasks/do-thing.md", "when": "2026-12-25T10:00:00-05:00"},
        tool_context,
    )
    assert "task-" in result
    mock_docket.add.assert_called_once()


async def test_schedule_bad_datetime(mock_docket: AsyncMock, tool_context: ToolContext):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {"prompt_file": "tasks/test.md", "when": "not-a-date"},
        tool_context,
    )
    assert "invalid datetime" in result


async def test_schedule_rejects_colon_in_key(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {
            "prompt_file": "tasks/test.md",
            "when": "2026-12-25T10:00:00-05:00",
            "key": "search:index:foo",
        },
        tool_context,
    )
    assert "reserved for system tasks" in result
    mock_docket.replace.assert_not_called()


async def test_schedule_rejects_builtin_task_key(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    async def reverie(  # pragma: no cover
        perpetual: Perpetual = Perpetual(every=timedelta(minutes=30), automatic=True),
    ) -> None: ...

    mock_docket.tasks = {"reverie": reverie}

    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {
            "prompt_file": "tasks/test.md",
            "when": "2026-12-25T10:00:00-05:00",
            "key": "reverie",
        },
        tool_context,
    )
    assert "built-in system task" in result
    mock_docket.replace.assert_not_called()


async def test_schedule_silent(mock_docket: AsyncMock, tool_context: ToolContext):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule",
        {
            "prompt_file": "tasks/quiet.md",
            "when": "2026-12-25T10:00:00-05:00",
            "silent": True,
        },
        tool_context,
    )
    assert "silently" in result


async def test_schedule_passes_thread_id(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    tool_context.thread_id = "parent_1"
    register_docket_tools(mock_docket, tool_context)
    await registry.execute(
        "schedule",
        {
            "prompt_file": "tasks/reply-in-thread.md",
            "when": "2026-12-25T10:00:00-05:00",
            "key": "thread-task",
        },
        tool_context,
    )
    mock_docket.replace.assert_called_once()
    call_kwargs = mock_docket.replace.return_value.call_args[1]
    assert call_kwargs["thread_id"] == "parent_1"


async def test_schedule_no_thread_by_default(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    register_docket_tools(mock_docket, tool_context)
    await registry.execute(
        "schedule",
        {
            "prompt_file": "tasks/do-thing.md",
            "when": "2026-12-25T10:00:00-05:00",
            "key": "no-thread",
        },
        tool_context,
    )
    call_kwargs = mock_docket.replace.return_value.call_args[1]
    assert call_kwargs["thread_id"] == ""


# --- schedule_every tests ---


async def test_schedule_every_with_duration(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule_every",
        {
            "prompt_file": "tasks/check-status.md",
            "every": "PT30M",
            "key": "status-check",
        },
        tool_context,
    )
    assert "status-check" in result
    assert "30m" in result.lower() or "30 min" in result.lower()
    mock_docket.replace.assert_called_once()


async def test_schedule_every_with_cron(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule_every",
        {"prompt_file": "tasks/standup.md", "every": "0 9 * * 1-5", "key": "standup"},
        tool_context,
    )
    assert "standup" in result
    assert "cron" in result.lower()
    mock_docket.replace.assert_called_once()


async def test_schedule_every_invalid_expression(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule_every",
        {"prompt_file": "tasks/test.md", "every": "not-valid", "key": "bad"},
        tool_context,
    )
    assert "error" in result.lower()


async def test_schedule_every_invalid_timezone(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule_every",
        {
            "prompt_file": "tasks/test.md",
            "every": "0 9 * * *",
            "key": "tz-bad",
            "timezone": "Fake/Zone",
        },
        tool_context,
    )
    assert "error" in result.lower()


async def test_schedule_every_silent_clears_room(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule_every",
        {
            "prompt_file": "tasks/quiet-work.md",
            "every": "PT1H",
            "key": "quiet",
            "silent": True,
        },
        tool_context,
    )
    assert "silently" in result
    call_kwargs = mock_docket.replace.return_value.call_args[1]
    assert call_kwargs["room_id"] == ""


async def test_schedule_every_thread_passthrough(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    tool_context.thread_id = "parent_1"
    register_docket_tools(mock_docket, tool_context)
    await registry.execute(
        "schedule_every",
        {"prompt_file": "tasks/thread-work.md", "every": "PT30M", "key": "threaded"},
        tool_context,
    )
    call_kwargs = mock_docket.replace.return_value.call_args[1]
    assert call_kwargs["thread_id"] == "parent_1"


async def test_schedule_every_with_cron_shorthand(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule_every",
        {
            "prompt_file": "tasks/daily-check.md",
            "every": "@daily",
            "key": "daily-check",
        },
        tool_context,
    )
    assert "daily-check" in result
    mock_docket.replace.assert_called_once()


async def test_schedule_every_rejects_colon_in_key(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule_every",
        {
            "prompt_file": "tasks/test.md",
            "every": "PT30M",
            "key": "search:index:foo",
        },
        tool_context,
    )
    assert "reserved for system tasks" in result
    mock_docket.replace.assert_not_called()


async def test_schedule_every_rejects_builtin_task_key(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    async def backup(  # pragma: no cover
        perpetual: Perpetual = Perpetual(every=timedelta(minutes=5), automatic=True),
    ) -> None: ...

    mock_docket.tasks = {"backup": backup}

    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute(
        "schedule_every",
        {"prompt_file": "tasks/test.md", "every": "PT30M", "key": "backup"},
        tool_context,
    )
    assert "built-in system task" in result
    mock_docket.replace.assert_not_called()


# --- cancel_task tests ---


async def test_cancel_task(mock_docket: AsyncMock, tool_context: ToolContext):
    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("cancel_task", {"key": "old-task"}, tool_context)
    assert "Cancelled" in result
    mock_docket.cancel.assert_called_once_with("old-task")


# --- list_scheduled tests ---


async def test_list_scheduled_empty(mock_docket: AsyncMock, tool_context: ToolContext):
    snapshot = MagicMock()
    snapshot.future = []
    snapshot.running = []
    mock_docket.snapshot.return_value = snapshot

    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert result == "No scheduled tasks"


async def test_list_scheduled_with_tasks(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    future_task = MagicMock()
    future_task.key = "task-1"
    future_task.when = datetime(2026, 12, 25, 10, 0, tzinfo=UTC)
    future_task.kwargs = {"prompt_file": "tasks/do-thing.md"}

    running_task = MagicMock()
    running_task.key = "task-2"
    running_task.kwargs = {"prompt_file": "tasks/running-now.md"}

    snapshot = MagicMock()
    snapshot.future = [future_task]
    snapshot.running = [running_task]
    mock_docket.snapshot.return_value = snapshot

    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert "2 task(s)" in result
    assert "task-1" in result
    assert "task-2" in result
    assert "RUNNING" in result


async def test_list_scheduled_shows_every_for_recurring(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    future_task = MagicMock()
    future_task.key = "recurring-1"
    future_task.when = datetime(2026, 12, 25, 10, 0, tzinfo=UTC)
    future_task.kwargs = {"prompt_file": "tasks/check-in.md", "every": "PT30M"}

    snapshot = MagicMock()
    snapshot.future = [future_task]
    snapshot.running = []
    mock_docket.snapshot.return_value = snapshot

    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert "recurring-1" in result
    assert "every PT30M" in result or "PT30M" in result


async def test_list_scheduled_future_prompt(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    task = MagicMock()
    task.key = "task-1"
    task.when = datetime(2026, 12, 25, 10, 0, tzinfo=UTC)
    task.kwargs = {"prompt_file": "tasks/reminder.md"}

    snapshot = MagicMock()
    snapshot.future = [task]
    snapshot.running = []
    mock_docket.snapshot.return_value = snapshot

    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert "tasks/reminder.md" in result


async def test_list_scheduled_running_prompt(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    task = MagicMock()
    task.key = "task-r"
    task.kwargs = {"prompt_file": "tasks/reminder.md"}

    snapshot = MagicMock()
    snapshot.future = []
    snapshot.running = [task]
    mock_docket.snapshot.return_value = snapshot

    register_docket_tools(mock_docket, tool_context)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert "tasks/reminder.md" in result
    assert "RUNNING" in result
