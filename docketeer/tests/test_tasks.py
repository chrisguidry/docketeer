"""Tests for docket task handlers."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from anthropic import AuthenticationError

from docketeer import environment
from docketeer.brain import APOLOGY
from docketeer.prompt import BrainResponse, MessageContent
from docketeer.tasks import docketeer_tasks, nudge, nudge_every, parse_every

from .conftest import make_api_connection_error, make_auth_error


def test_collection_contains_nudge():
    assert nudge in docketeer_tasks


def test_collection_contains_nudge_every():
    assert nudge_every in docketeer_tasks


# --- parse_every tests ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PT30M", timedelta(minutes=30)),
        ("PT2H", timedelta(hours=2)),
        ("P1D", timedelta(days=1)),
        ("PT30S", timedelta(seconds=30)),
        ("PT1H30M", timedelta(hours=1, minutes=30)),
        ("P1DT12H", timedelta(days=1, hours=12)),
        ("P2DT3H15M45S", timedelta(days=2, hours=3, minutes=15, seconds=45)),
        ("pt30m", timedelta(minutes=30)),
    ],
)
def test_parse_every_durations(value: str, expected: timedelta):
    assert parse_every(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "0 9 * * *",
        "@daily",
        "",
        "not-a-duration",
        "30m",
    ],
)
def test_parse_every_non_durations_return_none(value: str):
    assert parse_every(value) is None


async def test_nudge_with_room_sends_message():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="reminder sent")
    client = AsyncMock()

    await nudge(prompt="hey there", room_id="room123", brain=brain, client=client)

    brain.process.assert_called_once()
    call_args = brain.process.call_args
    assert call_args[0][0] == "room123"
    content: MessageContent = call_args[0][1]
    assert content.username == "system"
    assert content.text == "hey there"

    client.send_message.assert_called_once_with(
        "room123", "reminder sent", thread_id=""
    )


async def test_nudge_silent_uses_tasks_room():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="done")
    client = AsyncMock()

    await nudge(prompt="do reflection", room_id="", brain=brain, client=client)

    brain.process.assert_called_once()
    assert brain.process.call_args[0][0] == "__tasks__"
    client.send_message.assert_not_called()


async def test_nudge_no_send_on_empty_response():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="")
    client = AsyncMock()

    await nudge(prompt="silent work", room_id="room123", brain=brain, client=client)
    client.send_message.assert_not_called()


# --- Error handling tests ---


async def test_nudge_brain_error_sends_apology_to_room():
    """When brain.process raises, nudge sends an apology if room_id is set."""
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()

    await nudge(prompt="do stuff", room_id="room123", brain=brain, client=client)
    client.send_message.assert_called_once_with("room123", APOLOGY, thread_id="")


async def test_nudge_silent_error_logged_only():
    """When brain.process raises and there's no room_id, no message is sent."""
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()

    await nudge(prompt="do stuff", room_id="", brain=brain, client=client)
    client.send_message.assert_not_called()


async def test_nudge_auth_error_propagates():
    """AuthenticationError propagates from nudge."""
    brain = AsyncMock()
    brain.process.side_effect = make_auth_error()
    client = AsyncMock()

    with pytest.raises(AuthenticationError):
        await nudge(prompt="do stuff", room_id="room123", brain=brain, client=client)


# --- Thread support ---


async def test_nudge_with_thread_sends_to_thread():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="thread reply")
    client = AsyncMock()

    await nudge(
        prompt="reply here",
        room_id="room123",
        thread_id="parent_1",
        brain=brain,
        client=client,
    )

    content: MessageContent = brain.process.call_args[0][1]
    assert content.thread_id == "parent_1"

    client.send_message.assert_called_once_with(
        "room123", "thread reply", thread_id="parent_1"
    )


async def test_nudge_without_thread_sends_to_channel():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="channel reply")
    client = AsyncMock()

    await nudge(prompt="reply here", room_id="room123", brain=brain, client=client)

    content: MessageContent = brain.process.call_args[0][1]
    assert content.thread_id == ""

    client.send_message.assert_called_once_with(
        "room123", "channel reply", thread_id=""
    )


async def test_nudge_thread_error_sends_apology_to_thread():
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()

    await nudge(
        prompt="do stuff",
        room_id="room123",
        thread_id="parent_1",
        brain=brain,
        client=client,
    )
    client.send_message.assert_called_once_with(
        "room123", APOLOGY, thread_id="parent_1"
    )


# --- nudge_every tests ---


async def test_nudge_every_with_room_sends_message():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="recurring reply")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt="check status",
        every="PT30M",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    brain.process.assert_called_once()
    content: MessageContent = brain.process.call_args[0][1]
    assert content.text == "check status"
    client.send_message.assert_called_once_with(
        "room123", "recurring reply", thread_id=""
    )


async def test_nudge_every_duration_calls_perpetual_after():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt="check",
        every="PT30M",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    perpetual.after.assert_called_once_with(timedelta(minutes=30))


async def test_nudge_every_cron_calls_perpetual_at():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt="morning check",
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


async def test_nudge_every_cron_with_timezone():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt="morning check",
        every="0 9 * * *",
        timezone="America/New_York",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    perpetual.at.assert_called_once()
    next_time = perpetual.at.call_args[0][0]
    assert next_time.hour == 9


async def test_nudge_every_silent_no_message():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="done")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt="silent work",
        every="PT1H",
        room_id="",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    brain.process.assert_called_once()
    assert brain.process.call_args[0][0] == "__tasks__"
    client.send_message.assert_not_called()


async def test_nudge_every_error_sends_apology():
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt="check",
        every="PT30M",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    client.send_message.assert_called_once_with("room123", APOLOGY, thread_id="")
    perpetual.after.assert_called_once()


async def test_nudge_every_error_silent_still_reschedules():
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt="check",
        every="PT30M",
        room_id="",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    client.send_message.assert_not_called()
    perpetual.after.assert_called_once()


async def test_nudge_every_auth_error_propagates():
    brain = AsyncMock()
    brain.process.side_effect = make_auth_error()
    client = AsyncMock()
    perpetual = MagicMock()

    with pytest.raises(AuthenticationError):
        await nudge_every(
            prompt="check",
            every="PT30M",
            room_id="room123",
            brain=brain,
            client=client,
            perpetual=perpetual,
        )


async def test_nudge_every_with_thread():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="thread reply")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt="check",
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


async def test_nudge_every_cron_defaults_to_local_timezone():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    local_tz = environment.local_timezone()

    with patch(
        "docketeer.tasks.environment.local_timezone", return_value=local_tz
    ) as mock_tz:
        await nudge_every(
            prompt="morning check",
            every="0 9 * * *",
            timezone="",
            room_id="room123",
            brain=brain,
            client=client,
            perpetual=perpetual,
        )
        mock_tz.assert_called_once()

    perpetual.at.assert_called_once()


async def test_nudge_every_cron_explicit_timezone_honored():
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt="morning check",
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
