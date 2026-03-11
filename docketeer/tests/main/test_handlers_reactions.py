"""Tests for reaction handling in the message processing loop."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from docketeer.brain import APOLOGY, Brain
from docketeer.brain.backend import BackendAuthError
from docketeer.chat import IncomingReaction, RoomKind, RoomMessage
from docketeer.handlers import handle_reaction, process_messages
from docketeer.testing import MemoryChat

from ..conftest import (
    FakeMessage,
    FakeMessages,
    make_backend_auth_error,
    make_text_block,
)


def _make_reaction(
    emoji: str = ":thumbsup:",
    room_id: str = "room1",
    reacted_msg_id: str = "m0",
) -> IncomingReaction:
    return IncomingReaction(
        user_id="u1",
        username="alice",
        display_name="Alice",
        emoji=emoji,
        reacted_msg_id=reacted_msg_id,
        room_id=room_id,
        kind=RoomKind.direct,
        timestamp=datetime(2026, 3, 11, 12, 0, tzinfo=UTC),
    )


def _preload_room(brain: Brain, room_id: str = "room1") -> None:
    brain.load_history(
        room_id,
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="x",
            )
        ],
    )


async def test_handle_reaction_sends_to_brain(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """A reaction is formatted and processed by the brain."""
    _preload_room(brain)
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="On it!")])]

    await handle_reaction(chat, brain, _make_reaction())

    assert len(chat.sent_messages) == 1
    assert chat.sent_messages[0].text == "On it!"


async def test_handle_reaction_no_brain_emoji(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """Reactions don't trigger a :brain: reaction on any message."""
    _preload_room(brain)
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="ok")])]

    await handle_reaction(chat, brain, _make_reaction())

    assert chat.reactions == []


async def test_handle_reaction_loads_history_for_new_room(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """History is loaded when a reaction arrives for an unknown room."""
    chat._room_messages["new_room"] = [
        RoomMessage(
            message_id="m0",
            timestamp=datetime(2026, 2, 6, 15, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="old msg",
        )
    ]
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="ok")])]

    await handle_reaction(chat, brain, _make_reaction(room_id="new_room"))

    assert brain.has_history("new_room")


async def test_handle_reaction_empty_response_not_sent(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """When the brain returns empty text, no message is sent."""
    _preload_room(brain)
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="")])]

    await handle_reaction(chat, brain, _make_reaction())

    assert chat.sent_messages == []


async def test_handle_reaction_brain_error_sends_apology(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """When brain.process raises, handle_reaction sends an apology."""
    _preload_room(brain)

    with patch.object(brain, "process", side_effect=RuntimeError("boom")):
        await handle_reaction(chat, brain, _make_reaction())

    assert len(chat.sent_messages) == 1
    assert chat.sent_messages[0].text == APOLOGY


async def test_handle_reaction_auth_error_propagates(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """BackendAuthError propagates through handle_reaction."""
    _preload_room(brain)

    with patch.object(brain, "process", side_effect=make_backend_auth_error()):
        with pytest.raises(BackendAuthError):
            await handle_reaction(chat, brain, _make_reaction())


async def test_handle_reaction_send_failure_does_not_crash(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """If send_message fails after brain processes a reaction, it doesn't crash."""
    _preload_room(brain)
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="reply")])]

    with patch.object(
        chat, "send_message", side_effect=ConnectionError("network down")
    ):
        await handle_reaction(chat, brain, _make_reaction())


async def test_process_messages_handles_reaction(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """Reactions arriving via incoming_messages are dispatched to handle_reaction."""
    _preload_room(brain)
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Approved!")])]

    await chat._incoming.put(_make_reaction())
    await chat._incoming.put(None)

    await process_messages(chat, brain)

    assert len(chat.sent_messages) == 1
    assert chat.sent_messages[0].text == "Approved!"
