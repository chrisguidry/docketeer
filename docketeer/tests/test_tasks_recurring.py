"""Tests for recurring (nudge_every) task handlers."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from docketeer import environment
from docketeer.brain import APOLOGY
from docketeer.brain.backend import BackendAuthError
from docketeer.prompt import BrainResponse, MessageContent
from docketeer.tasks import nudge_every

from .conftest import make_api_connection_error, make_backend_auth_error


async def test_nudge_every_with_room_sends_message(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="recurring reply")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["check_status"],
        every="PT30M",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
        task_key="check-status",
    )

    brain.process.assert_called_once()
    assert brain.process.call_args[0][0] == "__task__:check-status"
    content: MessageContent = brain.process.call_args[0][1]
    assert content.text == "check status"
    assert brain.process.call_args[1]["chat_room"] == "room123"
    client.send_message.assert_called_once_with(
        "room123", "recurring reply", thread_id=""
    )


async def test_nudge_every_duration_calls_perpetual_after(
    workspace: Path, task_files: dict
):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["check"],
        every="PT30M",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    perpetual.after.assert_called_once_with(timedelta(minutes=30))


async def test_nudge_every_cron_calls_perpetual_at(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["morning_check"],
        every="0 9 * * *",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    perpetual.at.assert_called_once()
    next_time = perpetual.at.call_args[0][0]
    assert next_time.minute == 0
    assert next_time.hour == 9


async def test_nudge_every_cron_with_timezone(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["morning_check"],
        every="0 9 * * *",
        timezone="Etc/UTC",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    perpetual.at.assert_called_once()
    next_time = perpetual.at.call_args[0][0]
    assert next_time.hour == 9


async def test_nudge_every_silent_no_message(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="done")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["silent_work"],
        every="PT1H",
        room_id="",
        brain=brain,
        client=client,
        perpetual=perpetual,
        task_key="silent-work",
    )

    brain.process.assert_called_once()
    assert brain.process.call_args[0][0] == "__task__:silent-work"
    client.send_message.assert_not_called()


async def test_nudge_every_error_sends_apology(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["check"],
        every="PT30M",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    client.send_message.assert_called_once_with("room123", APOLOGY, thread_id="")
    perpetual.after.assert_called_once()


async def test_nudge_every_error_silent_still_reschedules(
    workspace: Path, task_files: dict
):
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["check"],
        every="PT30M",
        room_id="",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    client.send_message.assert_not_called()
    perpetual.after.assert_called_once()


async def test_nudge_every_auth_error_propagates(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.side_effect = make_backend_auth_error()
    client = AsyncMock()
    perpetual = MagicMock()

    with pytest.raises(BackendAuthError):
        await nudge_every(
            prompt_file=task_files["check"],
            every="PT30M",
            room_id="room123",
            brain=brain,
            client=client,
            perpetual=perpetual,
        )


async def test_nudge_every_with_thread(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="thread reply")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["check"],
        every="PT30M",
        room_id="room123",
        thread_id="parent_1",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    content: MessageContent = brain.process.call_args[0][1]
    assert content.thread_id == "parent_1"
    client.send_message.assert_called_once_with(
        "room123", "thread reply", thread_id="parent_1"
    )


# --- timezone default tests ---


async def test_nudge_every_cron_defaults_to_local_timezone(
    workspace: Path, task_files: dict
):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    local_tz = environment.local_timezone()

    with patch(
        "docketeer.tasks.environment.local_timezone", return_value=local_tz
    ) as mock_tz:
        await nudge_every(
            prompt_file=task_files["morning_check"],
            every="0 9 * * *",
            timezone="",
            room_id="room123",
            brain=brain,
            client=client,
            perpetual=perpetual,
        )
        mock_tz.assert_called_once()

    perpetual.at.assert_called_once()


async def test_nudge_every_cron_explicit_timezone_honored(
    workspace: Path, task_files: dict
):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["morning_check"],
        every="0 9 * * *",
        timezone="America/New_York",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    perpetual.at.assert_called_once()
    next_time = perpetual.at.call_args[0][0]
    assert next_time.tzinfo == ZoneInfo("America/New_York")
