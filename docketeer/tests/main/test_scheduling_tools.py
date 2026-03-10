"""Tests for scheduling and antenna tools (list_scheduled, list_bands)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from docketeer.antenna import Antenna, register_antenna_tools
from docketeer.tasks import register_scheduling_tools
from docketeer.testing import MemoryBand
from docketeer.tools import ToolContext, registry


def _make_antenna(bands: dict | None = None) -> Antenna:
    """Build a minimal Antenna mock for tool registration."""
    antenna = Antenna.__new__(Antenna)
    antenna._bands = bands or {}
    antenna._tunings = {}
    antenna._tasks = {}
    return antenna


# --- list_scheduled tests ---


async def test_list_scheduled_empty(mock_docket: AsyncMock, tool_context: ToolContext):
    snapshot = MagicMock()
    snapshot.future = []
    snapshot.running = []
    mock_docket.snapshot.return_value = snapshot

    register_scheduling_tools(mock_docket)
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

    register_scheduling_tools(mock_docket)
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

    register_scheduling_tools(mock_docket)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert "recurring-1" in result
    assert "PT30M" in result


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

    register_scheduling_tools(mock_docket)
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

    register_scheduling_tools(mock_docket)
    result = await registry.execute("list_scheduled", {}, tool_context)
    assert "tasks/reminder.md" in result
    assert "RUNNING" in result


# --- list_bands tests ---


async def test_list_bands_empty(mock_docket: AsyncMock, tool_context: ToolContext):
    register_antenna_tools(_make_antenna())
    result = await registry.execute("list_bands", {}, tool_context)
    assert "No bands available" in result


async def test_list_bands_with_bands(mock_docket: AsyncMock, tool_context: ToolContext):
    band = MemoryBand(name="wicket")
    band.description = "SSE webhook relay"
    register_antenna_tools(_make_antenna(bands={"wicket": band}))
    result = await registry.execute("list_bands", {}, tool_context)
    assert "1 band(s)" in result
    assert "wicket" in result
    assert "SSE webhook relay" in result


async def test_list_bands_no_description(
    mock_docket: AsyncMock, tool_context: ToolContext
):
    band = MemoryBand(name="simple")
    register_antenna_tools(_make_antenna(bands={"simple": band}))
    result = await registry.execute("list_bands", {}, tool_context)
    assert "simple" in result
