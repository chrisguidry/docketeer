"""Tests for intermediate text delivery and interruption wiring in handle_message."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

from docketeer.brain import Brain
from docketeer.chat import IncomingMessage, RoomMessage
from docketeer.handlers import handle_message
from docketeer.testing import MemoryChat

from ..conftest import (
    FakeMessage,
    FakeMessages,
    make_text_block,
    make_tool_use_block,
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


def _make_incoming(room_id: str = "room1") -> IncomingMessage:
    return IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id=room_id,
        is_direct=True,
    )


async def test_handle_message_intermediate_text_sent(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """Intermediate text from tool rounds appears as separate chat messages."""
    _preload_room(brain)
    fake_messages.responses = [
        FakeMessage(
            content=[
                make_text_block(text="Let me check..."),
                make_tool_use_block(name="list_files", input={"path": ""}),
            ],
        ),
        FakeMessage(content=[make_text_block(text="Here's what I found.")]),
    ]

    await handle_message(chat, brain, _make_incoming())
    texts = [m.text for m in chat.sent_messages]
    assert texts == ["Let me check...", "Here's what I found."]


async def test_handle_message_no_intermediate_text_on_text_only(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """A simple text reply produces exactly one sent message."""
    _preload_room(brain)
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Just a reply.")]),
    ]

    await handle_message(chat, brain, _make_incoming())
    assert len(chat.sent_messages) == 1
    assert chat.sent_messages[0].text == "Just a reply."


async def test_handle_message_interrupted_skips_final_response(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """When interrupted, intermediate text is sent but no final response."""
    _preload_room(brain)
    fake_messages.responses = [
        FakeMessage(
            content=[
                make_text_block(text="Let me check..."),
                make_tool_use_block(id="t1", name="list_files", input={"path": ""}),
            ],
        ),
        FakeMessage(
            content=[
                make_tool_use_block(id="t2", name="list_files", input={"path": ""}),
            ],
        ),
        FakeMessage(content=[make_text_block(text="Should not appear.")]),
    ]

    interrupted = asyncio.Event()

    original_send = chat.send_message

    async def send_and_interrupt(room_id: str, text: str, **kwargs: object) -> None:
        await original_send(room_id, text)
        if text == "Let me check...":
            interrupted.set()

    with patch.object(chat, "send_message", side_effect=send_and_interrupt):
        await handle_message(chat, brain, _make_incoming(), interrupted=interrupted)

    texts = [m.text for m in chat.sent_messages]
    assert texts == ["Let me check..."]
