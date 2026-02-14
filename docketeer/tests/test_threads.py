"""Tests for thread support across the chat abstraction."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from docketeer.brain import Brain
from docketeer.chat import IncomingMessage, RoomKind, RoomMessage
from docketeer.handlers import build_content, handle_message, send_response
from docketeer.main import _format_room_message, _register_core_chat_tools
from docketeer.prompt import BrainResponse
from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext, registry

from .conftest import FakeMessage, FakeMessages, make_text_block


@pytest.fixture(autouse=True)
def _save_registry() -> Iterator[None]:
    original_tools = registry._tools.copy()
    original_schemas = registry._schemas.copy()
    yield
    registry._tools = original_tools
    registry._schemas = original_schemas


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, room_id="room1")


@pytest.fixture()
def chat() -> MemoryChat:
    return MemoryChat()


@pytest.fixture()
def _register_tools(chat: MemoryChat) -> None:
    _register_core_chat_tools(chat)


# --- Data model: thread_id on messages ---


def test_incoming_message_thread_id_default():
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id="r1",
        kind=RoomKind.direct,
    )
    assert msg.thread_id == ""


def test_incoming_message_thread_id_set():
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id="r1",
        kind=RoomKind.direct,
        thread_id="parent_msg_1",
    )
    assert msg.thread_id == "parent_msg_1"


def test_room_message_thread_id_default():
    msg = RoomMessage(
        message_id="m1",
        timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
        username="alice",
        display_name="Alice",
        text="hello",
    )
    assert msg.thread_id == ""


def test_room_message_thread_id_set():
    msg = RoomMessage(
        message_id="m1",
        timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
        username="alice",
        display_name="Alice",
        text="hello",
        thread_id="parent_msg_1",
    )
    assert msg.thread_id == "parent_msg_1"


# --- ToolContext: thread_id ---


def test_tool_context_thread_id_default(workspace: Path):
    ctx = ToolContext(workspace=workspace)
    assert ctx.thread_id == ""


def test_tool_context_thread_id_set(workspace: Path):
    ctx = ToolContext(workspace=workspace, thread_id="t1")
    assert ctx.thread_id == "t1"


# --- MemoryChat: captures thread_id ---


async def test_memory_chat_send_message_captures_thread_id(chat: MemoryChat):
    await chat.send_message("room1", "hello", thread_id="t1")
    assert chat.sent_messages[0].thread_id == "t1"


async def test_memory_chat_send_message_default_thread_id(chat: MemoryChat):
    await chat.send_message("room1", "hello")
    assert chat.sent_messages[0].thread_id == ""


async def test_memory_chat_upload_file_captures_thread_id(
    chat: MemoryChat, tmp_path: Path
):
    f = tmp_path / "test.txt"
    f.write_text("content")
    await chat.upload_file("room1", str(f), thread_id="t1")
    assert chat.uploaded_files[0].thread_id == "t1"


async def test_memory_chat_upload_file_default_thread_id(
    chat: MemoryChat, tmp_path: Path
):
    f = tmp_path / "test.txt"
    f.write_text("content")
    await chat.upload_file("room1", str(f))
    assert chat.uploaded_files[0].thread_id == ""


# --- Handlers: thread_id routing ---


async def test_handle_message_routes_thread_reply(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="old",
            )
        ],
    )
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Got it!")])]

    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id="room1",
        kind=RoomKind.direct,
        thread_id="parent_msg_1",
    )
    await handle_message(chat, brain, msg)
    assert len(chat.sent_messages) >= 1
    last = chat.sent_messages[-1]
    assert last.thread_id == "parent_msg_1"


async def test_handle_message_channel_message_no_thread(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="old",
            )
        ],
    )
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Reply")])]

    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id="room1",
        kind=RoomKind.direct,
    )
    await handle_message(chat, brain, msg)
    assert len(chat.sent_messages) >= 1
    last = chat.sent_messages[-1]
    assert last.thread_id == ""


async def test_send_response_passes_thread_id(chat: MemoryChat):
    await send_response(chat, "room1", BrainResponse(text="reply"), thread_id="t1")
    assert chat.sent_messages[0].thread_id == "t1"


# --- room_messages formatting ---


def test_format_room_message_with_thread():
    msg = RoomMessage(
        message_id="m1",
        timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
        username="alice",
        display_name="Alice",
        text="reply in thread",
        thread_id="parent_msg_1",
    )
    formatted = _format_room_message(msg)
    assert "[thread:parent_msg_1]" in formatted


def test_format_room_message_without_thread():
    msg = RoomMessage(
        message_id="m1",
        timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
        username="alice",
        display_name="Alice",
        text="channel message",
    )
    formatted = _format_room_message(msg)
    assert "thread" not in formatted


# --- send_message tool ---


@pytest.mark.usefixtures("_register_tools")
async def test_send_message_tool_to_thread(chat: MemoryChat, tool_context: ToolContext):
    tool_context.room_id = "room1"
    result = await registry.execute(
        "send_message", {"text": "hello", "thread_id": "t1"}, tool_context
    )
    assert "Sent" in result
    assert chat.sent_messages[0].thread_id == "t1"
    assert chat.sent_messages[0].room_id == "room1"


@pytest.mark.usefixtures("_register_tools")
async def test_send_message_tool_to_channel(
    chat: MemoryChat, tool_context: ToolContext
):
    tool_context.room_id = "room1"
    result = await registry.execute("send_message", {"text": "hello"}, tool_context)
    assert "Sent" in result
    assert chat.sent_messages[0].thread_id == ""


@pytest.mark.usefixtures("_register_tools")
async def test_send_message_tool_custom_room(
    chat: MemoryChat, tool_context: ToolContext
):
    tool_context.room_id = "room1"
    result = await registry.execute(
        "send_message", {"text": "hello", "room_id": "other-room"}, tool_context
    )
    assert "Sent" in result
    assert chat.sent_messages[0].room_id == "other-room"


# --- Brain: thread_id on tool context ---


async def test_brain_sets_thread_id_on_tool_context(
    brain: Brain, fake_messages: FakeMessages
):
    from docketeer.prompt import MessageContent

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

    content = MessageContent(
        username="alice",
        message_id="m1",
        timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
        text="hello",
        thread_id="parent_1",
    )
    await brain.process("room1", content)
    assert brain.tool_context.thread_id == "parent_1"


async def test_brain_clears_thread_id_for_channel_messages(
    brain: Brain, fake_messages: FakeMessages
):
    from docketeer.prompt import MessageContent

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

    content = MessageContent(
        username="alice",
        message_id="m1",
        timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
        text="hello",
    )
    await brain.process("room1", content)
    assert brain.tool_context.thread_id == ""


# --- build_content passes thread_id ---


async def test_build_content_includes_thread_id(chat: MemoryChat):
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id="r1",
        kind=RoomKind.direct,
        thread_id="t1",
    )
    content = await build_content(chat, msg)
    assert content.thread_id == "t1"


async def test_build_content_empty_thread_id(chat: MemoryChat):
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id="r1",
        kind=RoomKind.direct,
    )
    content = await build_content(chat, msg)
    assert content.thread_id == ""
