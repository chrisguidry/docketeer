"""Tests for the digest module."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from docketeer.chat import RoomInfo, RoomKind, RoomMessage
from docketeer.digest import (
    _format_room_messages,
    build_conversation_digest,
)
from docketeer.testing import MemoryChat

EST = timezone(timedelta(hours=-5))
BASE_TIME = datetime(2026, 3, 6, 10, 0, 0, tzinfo=EST)


@pytest.fixture()
def chat() -> MemoryChat:
    return MemoryChat()


def _make_room(
    room_id: str = "general",
    name: str = "general",
    kind: RoomKind = RoomKind.public,
    members: list[str] | None = None,
) -> RoomInfo:
    return RoomInfo(room_id=room_id, kind=kind, members=members or [], name=name)


def _make_message(
    username: str = "alice",
    text: str = "hello",
    minutes_offset: int = 0,
) -> RoomMessage:
    return RoomMessage(
        message_id=f"msg-{minutes_offset}",
        timestamp=BASE_TIME + timedelta(minutes=minutes_offset),
        username=username,
        display_name=username.title(),
        text=text,
    )


async def test_digest_no_activity_when_no_rooms(chat: MemoryChat):
    result = await build_conversation_digest(chat, None, since=BASE_TIME)
    assert result == "No chat activity since last reverie."


async def test_digest_skips_internal_rooms(chat: MemoryChat):
    chat._rooms = [
        _make_room("__task__:reverie", "__task__:reverie"),
        _make_room("__task__:consolidation", "__task__:consolidation"),
    ]
    result = await build_conversation_digest(chat, None, since=BASE_TIME)
    assert result == "No chat activity since last reverie."


async def test_digest_no_activity_when_no_recent_messages(chat: MemoryChat):
    room = _make_room()
    chat._rooms = [room]
    chat._room_messages["general"] = [
        _make_message(minutes_offset=-60),
    ]
    since = BASE_TIME - timedelta(minutes=30)
    result = await build_conversation_digest(chat, None, since=since)
    assert result == "No chat activity since last reverie."


async def test_digest_includes_full_messages_under_limit(chat: MemoryChat):
    room = _make_room()
    chat._rooms = [room]
    chat._room_messages["general"] = [
        _make_message("alice", "Hey, did you see the update?", 0),
        _make_message("bob", "Yeah, looks great!", 5),
    ]
    since = BASE_TIME - timedelta(minutes=1)
    result = await build_conversation_digest(chat, None, since=since)
    assert "## #general (public)" in result
    assert "@alice: Hey, did you see the update?" in result
    assert "@bob: Yeah, looks great!" in result


async def test_digest_summarizes_large_rooms(chat: MemoryChat):
    room = _make_room()
    chat._rooms = [room]
    chat._room_messages["general"] = [
        _make_message("alice", "x" * 500, i) for i in range(20)
    ]
    since = BASE_TIME - timedelta(minutes=1)

    backend = AsyncMock()
    backend.utility_complete.return_value = "Alice posted many messages."

    result = await build_conversation_digest(
        chat, backend, since=since, room_char_limit=100
    )
    assert "[summarized]" in result
    assert "Alice posted many messages." in result
    backend.utility_complete.assert_called_once()


async def test_digest_formats_participants(chat: MemoryChat):
    room = _make_room()
    chat._rooms = [room]
    chat._room_messages["general"] = [
        _make_message("bob", "hi", 0),
        _make_message("alice", "hey", 1),
        _make_message("bob", "sup", 2),
    ]
    since = BASE_TIME - timedelta(minutes=1)
    result = await build_conversation_digest(chat, None, since=since)
    assert "Participants: alice, bob" in result


async def test_digest_includes_room_kind(chat: MemoryChat):
    room = _make_room(kind=RoomKind.direct, name="alice-bob")
    chat._rooms = [room]
    chat._room_messages["general"] = [
        _make_message("alice", "hey", 0),
    ]
    since = BASE_TIME - timedelta(minutes=1)
    result = await build_conversation_digest(chat, None, since=since)
    assert "(direct)" in result


async def test_digest_handles_fetch_failure(chat: MemoryChat):
    room_ok = _make_room("ok-room", "ok-room")
    room_bad = _make_room("bad-room", "bad-room")
    chat._rooms = [room_ok, room_bad]
    chat._room_messages["ok-room"] = [_make_message("alice", "works", 0)]

    original_fetch = chat.fetch_messages

    async def flaky_fetch(
        room_id: str,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        count: int = 50,
    ) -> list[RoomMessage]:
        if room_id == "bad-room":
            raise ConnectionError("network down")
        return await original_fetch(room_id, before=before, after=after, count=count)

    chat.fetch_messages = flaky_fetch  # type: ignore[assignment]

    since = BASE_TIME - timedelta(minutes=1)
    result = await build_conversation_digest(chat, None, since=since)
    assert "#ok-room" in result
    assert "bad-room" not in result


async def test_digest_handles_summarization_failure(chat: MemoryChat):
    room = _make_room()
    chat._rooms = [room]
    chat._room_messages["general"] = [
        _make_message("alice", "x" * 500, i) for i in range(20)
    ]
    since = BASE_TIME - timedelta(minutes=1)

    backend = AsyncMock()
    backend.utility_complete.side_effect = RuntimeError("LLM down")

    result = await build_conversation_digest(
        chat, backend, since=since, room_char_limit=100
    )
    assert "[...truncated]" in result


async def test_digest_handles_no_backend(chat: MemoryChat):
    room = _make_room()
    chat._rooms = [room]
    chat._room_messages["general"] = [
        _make_message("alice", "x" * 500, i) for i in range(20)
    ]
    since = BASE_TIME - timedelta(minutes=1)
    result = await build_conversation_digest(
        chat, None, since=since, room_char_limit=100
    )
    assert "[...truncated]" in result
    assert "[summarized]" not in result


async def test_digest_concurrent_fetches(chat: MemoryChat):
    for i in range(5):
        room = _make_room(f"room-{i}", f"room-{i}")
        chat._rooms.append(room)
        chat._room_messages[f"room-{i}"] = [
            _make_message("alice", f"msg in room {i}", 0),
        ]
    since = BASE_TIME - timedelta(minutes=1)
    result = await build_conversation_digest(chat, None, since=since)
    for i in range(5):
        assert f"#room-{i}" in result


def test_format_room_messages():
    room = _make_room()
    messages = [
        _make_message("alice", "first message", 0),
        _make_message("bob", "reply", 5),
    ]
    result = _format_room_messages(room, messages)
    assert "## #general (public)" in result
    assert "Participants: alice, bob" in result
    assert "@alice: first message" in result
    assert "+5m" in result
    assert "@bob: reply" in result


def test_format_room_messages_uses_room_id_when_no_name():
    room = RoomInfo(room_id="ABC123", kind=RoomKind.public, members=[], name="")
    messages = [_make_message("alice", "hi", 0)]
    result = _format_room_messages(room, messages)
    assert "## #ABC123 (public)" in result


async def test_digest_handles_list_rooms_failure():
    chat = AsyncMock()
    chat.list_rooms.side_effect = ConnectionError("network down")
    result = await build_conversation_digest(chat, None, since=BASE_TIME)
    assert result == ""


async def test_digest_empty_summary_falls_back_to_truncation(chat: MemoryChat):
    room = _make_room()
    chat._rooms = [room]
    chat._room_messages["general"] = [
        _make_message("alice", "x" * 500, i) for i in range(20)
    ]
    since = BASE_TIME - timedelta(minutes=1)

    backend = AsyncMock()
    backend.utility_complete.return_value = "   "

    result = await build_conversation_digest(
        chat, backend, since=since, room_char_limit=100
    )
    assert "[...truncated]" in result


async def test_digest_multiple_rooms(chat: MemoryChat):
    chat._rooms = [
        _make_room("general", "general"),
        _make_room("random", "random"),
    ]
    chat._room_messages["general"] = [_make_message("alice", "hi", 0)]
    chat._room_messages["random"] = [_make_message("bob", "hey", 0)]
    since = BASE_TIME - timedelta(minutes=1)
    result = await build_conversation_digest(chat, None, since=since)
    assert "#general" in result
    assert "#random" in result
