"""Tests for the room_messages tool and formatting."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from docketeer.chat import Attachment, RoomMessage
from docketeer.main import _register_core_chat_tools
from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext, registry


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
def _register_tool(chat: MemoryChat) -> None:
    _register_core_chat_tools(chat)


# --- MemoryChat.fetch_messages ---


async def test_memory_chat_fetch_messages_by_count(chat: MemoryChat):
    chat._room_messages["room1"] = [
        RoomMessage(
            message_id="m1",
            timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="hello",
        ),
        RoomMessage(
            message_id="m2",
            timestamp=datetime(2026, 2, 8, 12, 1, tzinfo=UTC),
            username="bob",
            display_name="Bob",
            text="hi there",
        ),
    ]
    result = await chat.fetch_messages("room1", count=1)
    assert len(result) == 1


async def test_memory_chat_fetch_messages_by_time_range(chat: MemoryChat):
    chat._room_messages["room1"] = [
        RoomMessage(
            message_id="m1",
            timestamp=datetime(2026, 2, 8, 10, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="morning",
        ),
        RoomMessage(
            message_id="m2",
            timestamp=datetime(2026, 2, 8, 14, 0, tzinfo=UTC),
            username="bob",
            display_name="Bob",
            text="afternoon",
        ),
    ]
    result = await chat.fetch_messages(
        "room1",
        after=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
    )
    assert len(result) == 1
    assert result[0].text == "afternoon"


async def test_memory_chat_fetch_messages_empty_room(chat: MemoryChat):
    result = await chat.fetch_messages("nonexistent")
    assert result == []


# --- room_messages tool ---


@pytest.mark.usefixtures("_register_tool")
async def test_room_messages_last_n(chat: MemoryChat, tool_context: ToolContext):
    chat._room_messages["room1"] = [
        RoomMessage(
            message_id="m1",
            timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="hello world",
        ),
    ]
    result = await registry.execute("room_messages", {"count": 10}, tool_context)
    assert "@alice" in result
    assert "hello world" in result
    assert "2026" in result


@pytest.mark.usefixtures("_register_tool")
async def test_room_messages_with_attachments(
    chat: MemoryChat, tool_context: ToolContext
):
    chat._room_messages["room1"] = [
        RoomMessage(
            message_id="m1",
            timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="check this out",
            attachments=[
                Attachment(
                    url="/file-upload/abc123/screenshot.png",
                    media_type="image/png",
                    title="screenshot.png",
                ),
            ],
        ),
    ]
    result = await registry.execute("room_messages", {}, tool_context)
    assert "screenshot.png" in result
    assert "image/png" in result
    assert "/file-upload/abc123/screenshot.png" in result


@pytest.mark.usefixtures("_register_tool")
async def test_room_messages_with_time_range(
    chat: MemoryChat, tool_context: ToolContext
):
    chat._room_messages["room1"] = [
        RoomMessage(
            message_id="m1",
            timestamp=datetime(2026, 2, 8, 10, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="morning message",
        ),
        RoomMessage(
            message_id="m2",
            timestamp=datetime(2026, 2, 8, 14, 0, tzinfo=UTC),
            username="bob",
            display_name="Bob",
            text="afternoon message",
        ),
    ]
    result = await registry.execute(
        "room_messages",
        {"after": "2026-02-08T12:00:00+00:00"},
        tool_context,
    )
    assert "afternoon message" in result
    assert "morning message" not in result


@pytest.mark.usefixtures("_register_tool")
async def test_room_messages_empty(chat: MemoryChat, tool_context: ToolContext):
    result = await registry.execute("room_messages", {}, tool_context)
    assert "No messages" in result


@pytest.mark.usefixtures("_register_tool")
async def test_room_messages_custom_room(chat: MemoryChat, tool_context: ToolContext):
    chat._room_messages["other-room"] = [
        RoomMessage(
            message_id="m1",
            timestamp=datetime(2026, 2, 8, 12, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="in another room",
        ),
    ]
    result = await registry.execute(
        "room_messages", {"room_id": "other-room"}, tool_context
    )
    assert "in another room" in result
