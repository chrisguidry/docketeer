"""Tests for docket task handlers."""

from unittest.mock import AsyncMock

from docketeer.prompt import BrainResponse, MessageContent
from docketeer.tasks import docketeer_tasks, nudge


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

    client.send_message.assert_called_once_with("room123", "reminder sent")


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
