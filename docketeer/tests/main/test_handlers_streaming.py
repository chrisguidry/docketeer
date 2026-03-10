"""Tests for intermediate text delivery and interruption wiring in handle_message."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from docketeer.brain import Brain
from docketeer.chat import IncomingMessage, RoomKind, RoomMessage
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
        kind=RoomKind.direct,
    )


class _StreamingChat(MemoryChat):
    def __init__(
        self, fail_after_start: bool = False, fail_on_stop: bool = False
    ) -> None:
        super().__init__()
        self.stream_events: list[tuple[str, str]] = []
        self._stream_handle = object()
        self._fail_after_start = fail_after_start
        self._fail_on_stop = fail_on_stop

    async def start_reply_stream(
        self,
        msg: IncomingMessage,
        thread_id: str,
        text: str,
    ) -> Any | None:
        self.stream_events.append(("start", text))
        return self._stream_handle

    async def append_reply_stream(self, stream: Any, text: str) -> None:
        assert stream is self._stream_handle
        if self._fail_after_start:
            raise RuntimeError("boom")
        self.stream_events.append(("append", text))

    async def stop_reply_stream(self, stream: Any) -> None:
        assert stream is self._stream_handle
        self.stream_events.append(("stop", ""))
        if self._fail_on_stop:
            raise RuntimeError("stop boom")


async def test_handle_message_intermediate_text_suppressed(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """Text from tool rounds is suppressed — only the final response is sent."""
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
    assert texts == ["Here's what I found."]


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
    """When interrupted during a tool round, the loop exits and no final response is sent."""
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
    interrupted.set()

    await handle_message(chat, brain, _make_incoming(), interrupted=interrupted)

    texts = [m.text for m in chat.sent_messages]
    assert texts == []


async def test_handle_message_streams_text_without_duplicate_final_send(
    brain: Brain, fake_messages: FakeMessages
):
    chat = _StreamingChat()
    _preload_room(brain)
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Just a reply.")])
    ]

    await handle_message(chat, brain, _make_incoming())

    assert chat.stream_events == [("start", "Just a reply."), ("stop", "")]
    assert chat.sent_messages == []


async def test_handle_message_appends_streamed_text_chunks(
    brain: Brain, fake_messages: FakeMessages
):
    chat = _StreamingChat()
    _preload_room(brain)
    fake_messages.responses = [
        FakeMessage(
            content=[make_text_block(text="Hello"), make_text_block(text=" world")]
        )
    ]

    await handle_message(chat, brain, _make_incoming())

    assert chat.stream_events == [
        ("start", "Hello"),
        ("append", " world"),
        ("stop", ""),
    ]
    assert chat.sent_messages == []


async def test_handle_message_stream_append_failure_falls_back_to_final_message(
    brain: Brain, fake_messages: FakeMessages
):
    chat = _StreamingChat(fail_after_start=True)
    _preload_room(brain)
    fake_messages.responses = [
        FakeMessage(
            content=[make_text_block(text="Hello"), make_text_block(text=" world")]
        )
    ]

    await handle_message(chat, brain, _make_incoming())

    assert chat.stream_events[0] == ("start", "Hello")
    assert chat.stream_events[-1] == ("stop", "")
    assert [m.text for m in chat.sent_messages] == ["Hello\n world"]


async def test_handle_message_stream_stop_failure_still_sends_no_duplicate_message(
    brain: Brain, fake_messages: FakeMessages
):
    chat = _StreamingChat(fail_on_stop=True)
    _preload_room(brain)
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Just a reply.")])
    ]

    await handle_message(chat, brain, _make_incoming())

    assert chat.stream_events == [("start", "Just a reply."), ("stop", "")]
    assert chat.sent_messages == []
