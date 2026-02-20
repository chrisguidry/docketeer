"""Tests for the process_messages() loop: normal processing, interruption on new message."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from docketeer.brain import Brain
from docketeer.brain.backend import BackendAuthError
from docketeer.chat import IncomingMessage, RoomKind, RoomMessage
from docketeer.handlers import _check_handle_result, process_messages
from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext, registry

from ..conftest import (
    FakeMessage,
    FakeMessages,
    make_backend_auth_error,
    make_text_block,
    make_tool_use_block,
)


def _make_incoming(
    text: str = "hello", room_id: str = "room1", message_id: str = "m1"
) -> IncomingMessage:
    return IncomingMessage(
        message_id=message_id,
        user_id="u1",
        username="alice",
        display_name="Alice",
        text=text,
        room_id=room_id,
        kind=RoomKind.direct,
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


async def test_process_messages_single_message(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """A single message is processed and the loop exits cleanly."""
    _preload_room(brain)
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]

    msg = _make_incoming()
    await chat._incoming.put(msg)
    await chat._incoming.put(None)  # signal end

    await process_messages(chat, brain)

    assert len(chat.sent_messages) == 1
    assert chat.sent_messages[0].text == "Hi!"


async def test_process_messages_multiple_sequential(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """Multiple messages are processed in order when they arrive sequentially."""
    _preload_room(brain)
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Reply 1")]),
        FakeMessage(content=[make_text_block(text="Reply 2")]),
    ]

    await chat._incoming.put(_make_incoming(text="first", message_id="m1"))
    await chat._incoming.put(_make_incoming(text="second", message_id="m2"))
    await chat._incoming.put(None)

    await process_messages(chat, brain)

    texts = [m.text for m in chat.sent_messages]
    assert texts == ["Reply 1", "Reply 2"]


async def test_process_messages_interruption(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """A new message arriving during a long tool loop interrupts the current processing."""
    _preload_room(brain)

    # Register a slow tool that yields to the event loop, giving the interrupt
    # message time to arrive via peek_task
    tool_entered = asyncio.Event()

    @registry.tool
    async def slow_tool(ctx: ToolContext) -> str:
        """A slow tool for testing."""
        tool_entered.set()
        await asyncio.sleep(0.1)
        return "done"

    # msg1 gets one tool round (slow_tool), then gets interrupted before round 2.
    # msg2 gets the next API response, which is a simple text reply.
    fake_messages.responses = [
        # msg1, round 1: tool call (slow, giving time for msg2 to arrive)
        FakeMessage(
            content=[make_tool_use_block(id="t1", name="slow_tool", input={})],
        ),
        # msg2 gets this (msg1 was interrupted before making another API call)
        FakeMessage(content=[make_text_block(text="Got your new message!")]),
    ]

    msg1 = _make_incoming(text="do long task", message_id="m1")
    msg2 = _make_incoming(text="actually, stop", message_id="m2")

    msg2_done = asyncio.Event()
    original_send = chat.send_message.__func__

    async def tracking_send(
        self: MemoryChat, room_id: str, text: str, **kwargs: object
    ) -> None:
        await original_send(self, room_id, text)
        msg2_done.set()

    chat.send_message = tracking_send.__get__(chat, MemoryChat)  # type: ignore[assignment]

    async def send_interrupt() -> None:
        await tool_entered.wait()
        await chat._incoming.put(msg2)
        await msg2_done.wait()
        await chat._incoming.put(None)

    await chat._incoming.put(msg1)
    interrupt_task = asyncio.create_task(send_interrupt())

    await process_messages(chat, brain)
    await interrupt_task

    texts = [m.text for m in chat.sent_messages]
    # msg1 was interrupted (no text sent), msg2 gets "Got your new message!"
    assert texts == ["Got your new message!"]


async def test_process_messages_waits_when_no_next(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """When handle finishes before the next message arrives, the loop waits gracefully."""
    _preload_room(brain)
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]

    msg = _make_incoming()
    await chat._incoming.put(msg)

    # Delay the None so next_msg is still pending when handle finishes
    async def delayed_none() -> None:
        await asyncio.sleep(0.1)
        await chat._incoming.put(None)

    done_task = asyncio.create_task(delayed_none())
    await process_messages(chat, brain)
    await done_task

    assert len(chat.sent_messages) == 1
    assert chat.sent_messages[0].text == "Hi!"


async def test_process_messages_auth_error_propagates(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """BackendAuthError from handle_message propagates through process_messages."""
    _preload_room(brain)

    await chat._incoming.put(_make_incoming())
    await chat._incoming.put(None)
    with patch.object(brain, "process", side_effect=make_backend_auth_error()):
        with pytest.raises(BackendAuthError):
            await process_messages(chat, brain)


async def test_process_messages_generic_error_logged(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """Non-auth errors are logged and processing continues."""
    _preload_room(brain)

    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Reply")])]

    # First message will raise, second will succeed
    call_count = 0
    original_process = brain.process

    async def failing_then_ok(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        return await original_process(*args, **kwargs)

    with patch.object(brain, "process", side_effect=failing_then_ok):
        await chat._incoming.put(_make_incoming(text="first", message_id="m1"))
        await chat._incoming.put(_make_incoming(text="second", message_id="m2"))
        await chat._incoming.put(None)
        await process_messages(chat, brain)

    # The error is logged, typing cleared, apology sent for first;
    # second processes normally
    texts = [m.text for m in chat.sent_messages]
    assert any("sorry" in t.lower() for t in texts)
    assert "Reply" in texts


async def test_check_handle_result_logs_generic_error():
    """_check_handle_result logs non-auth exceptions without raising."""

    async def failing() -> None:
        raise RuntimeError("oops")

    task: asyncio.Task[None] = asyncio.create_task(failing())
    with pytest.raises(RuntimeError):
        await task

    # Should not raise — just log
    _check_handle_result(task)
