"""Tests for docket task handlers."""

from unittest.mock import AsyncMock

import pytest
from anthropic import AuthenticationError

from docketeer.brain import APOLOGY
from docketeer.prompt import BrainResponse, MessageContent
from docketeer.tasks import docketeer_tasks, nudge

from .conftest import make_api_connection_error, make_auth_error


def test_collection_contains_nudge():
    assert nudge in docketeer_tasks


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
