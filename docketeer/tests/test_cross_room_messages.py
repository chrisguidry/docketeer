"""Tests for recording outgoing messages in conversation history."""

from datetime import UTC, datetime

from docketeer.brain import Brain
from docketeer.chat import RoomMessage
from docketeer.prompt import MessageParam
from docketeer.testing import MemoryChat


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


async def test_record_own_message_injects_into_existing_history(
    brain: Brain,
):
    """Messages sent to rooms with loaded history get recorded."""
    _preload_room(brain, "dm-room")
    await brain.record_own_message("dm-room", "hello from a task")

    messages = brain._conversations["dm-room"]
    assert messages[-1] == MessageParam(role="assistant", content="hello from a task")


async def test_record_own_message_skips_room_without_history(
    brain: Brain,
):
    """Messages to rooms with no loaded history are silently dropped."""
    await brain.record_own_message("unknown-room", "hello")
    assert "unknown-room" not in brain._conversations


async def test_record_own_message_skips_current_processing_room(
    brain: Brain,
):
    """Messages to the room currently being processed are already tracked."""
    brain.tool_context.line = "active-room"
    _preload_room(brain, "active-room")
    initial_count = len(brain._conversations["active-room"])

    await brain.record_own_message("active-room", "response text")

    assert len(brain._conversations["active-room"]) == initial_count


async def test_record_own_message_skips_duplicate(
    brain: Brain,
):
    """If the last message already matches, don't double-record."""
    _preload_room(brain, "dm-room")
    brain._conversations["dm-room"].append(
        MessageParam(role="assistant", content="already here")
    )

    await brain.record_own_message("dm-room", "already here")

    assistant_msgs = [
        m for m in brain._conversations["dm-room"] if m.role == "assistant"
    ]
    assert sum(1 for m in assistant_msgs if m.content == "already here") == 1


async def test_memory_chat_calls_on_message_sent_callback():
    """MemoryChat.send_message fires _on_message_sent when set."""
    chat = MemoryChat()
    calls: list[tuple[str, str]] = []

    async def recorder(room_id: str, text: str) -> None:
        calls.append((room_id, text))

    chat._on_message_sent = recorder
    await chat.send_message("room1", "hello")

    assert calls == [("room1", "hello")]


async def test_memory_chat_send_message_without_callback():
    """MemoryChat.send_message works fine with no callback set."""
    chat = MemoryChat()
    await chat.send_message("room1", "hello")
    assert len(chat.sent_messages) == 1
