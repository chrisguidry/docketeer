from datetime import UTC, datetime

from docketeer.brain import Brain
from docketeer.chat import ChatClient, IncomingMessage, RoomKind, RoomMessage
from docketeer.handlers import handle_message
from docketeer.testing import MemoryChat

from ..conftest import FakeMessage, FakeMessages, make_text_block


class _StatusChat(MemoryChat):
    def __init__(self, reply_thread: str = "") -> None:
        super().__init__()
        self.status_changes: list[tuple[str, str, str]] = []
        self._reply_thread = reply_thread

    async def reply_thread_id(self, msg: IncomingMessage) -> str:
        return self._reply_thread or msg.thread_id

    async def set_thread_status(
        self,
        room_id: str,
        thread_id: str,
        status: str,
    ) -> None:
        self.status_changes.append((room_id, thread_id, status))


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


async def test_handle_message_sets_and_clears_thread_status(
    brain: Brain, fake_messages: FakeMessages
):
    chat = _StatusChat(reply_thread="thread-1")
    brain.load_history(
        "room1",
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
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="ok")])]
    await handle_message(chat, brain, _make_incoming())
    assert chat.status_changes == [
        ("room1", "thread-1", "is thinking..."),
        ("room1", "thread-1", ""),
    ]


async def test_handle_message_uses_backend_reply_thread(
    brain: Brain, fake_messages: FakeMessages
):
    chat = _StatusChat(reply_thread="thread-1")
    brain.load_history(
        "room1",
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
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="ok")])]
    await handle_message(chat, brain, _make_incoming())
    assert chat.sent_messages[-1].thread_id == "thread-1"


async def test_chat_client_default_reply_thread_id_uses_incoming_thread(
    chat: MemoryChat,
):
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hi",
        room_id="room1",
        kind=RoomKind.direct,
        thread_id="thread-1",
    )
    assert await ChatClient.reply_thread_id(chat, msg) == "thread-1"


async def test_chat_client_default_set_thread_status_is_noop(chat: MemoryChat):
    assert (
        await ChatClient.set_thread_status(chat, "room1", "thread-1", "thinking")
        is None
    )


async def test_chat_client_default_append_reply_stream_is_noop(chat: MemoryChat):
    assert await ChatClient.append_reply_stream(chat, object(), "hello") is None


async def test_chat_client_default_stop_reply_stream_is_noop(chat: MemoryChat):
    assert await ChatClient.stop_reply_stream(chat, object()) is None
