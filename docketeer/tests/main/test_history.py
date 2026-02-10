"""Tests for history loading."""

from datetime import UTC, datetime

from docketeer.brain import Brain
from docketeer.chat import RoomInfo, RoomKind, RoomMessage
from docketeer.main import _filter_rooms, load_all_history
from docketeer.testing import MemoryChat


async def test_load_all_history(chat: MemoryChat, brain: Brain):
    chat._rooms = [
        RoomInfo(room_id="r1", kind=RoomKind.direct, members=["testbot", "alice"]),
        RoomInfo(room_id="r2", kind=RoomKind.direct, members=["testbot", "bob"]),
    ]
    chat._room_messages = {
        "r1": [
            RoomMessage(
                message_id="m1",
                timestamp=datetime(2026, 2, 6, 15, 0, tzinfo=UTC),
                username="alice",
                display_name="Alice",
                text="hi",
            )
        ],
        "r2": [
            RoomMessage(
                message_id="m2",
                timestamp=datetime(2026, 2, 6, 16, 0, tzinfo=UTC),
                username="bob",
                display_name="Bob",
                text="hey",
            )
        ],
    }
    await load_all_history(chat, brain)
    assert brain.has_history("r1")
    assert brain.has_history("r2")
    assert brain._room_info["r1"].kind is RoomKind.direct
    assert brain._room_info["r1"].members == ["testbot", "alice"]
    assert brain._room_info["r2"].members == ["testbot", "bob"]


async def test_load_all_history_filters_to_dms(chat: MemoryChat, brain: Brain):
    chat._rooms = [
        RoomInfo(room_id="r1", kind=RoomKind.direct, members=["testbot", "alice"]),
        RoomInfo(
            room_id="r2",
            kind=RoomKind.public,
            members=["testbot", "bob"],
            name="general",
        ),
    ]
    chat._room_messages = {
        "r1": [
            RoomMessage(
                message_id="m1",
                timestamp=datetime(2026, 2, 6, 15, 0, tzinfo=UTC),
                username="alice",
                display_name="Alice",
                text="hi",
            )
        ],
    }
    await load_all_history(chat, brain)
    assert brain.has_history("r1")
    assert not brain.has_history("r2")


def test_filter_rooms_drops_self_dms():
    rooms = [
        RoomInfo(room_id="dm1", kind=RoomKind.direct, members=["bot", "alice"]),
        RoomInfo(room_id="self", kind=RoomKind.direct, members=["bot"]),
        RoomInfo(room_id="ch1", kind=RoomKind.public, members=["bot"], name="general"),
    ]
    filtered = _filter_rooms(rooms, "bot")
    ids = [r.room_id for r in filtered]
    assert "dm1" in ids
    assert "self" not in ids
    assert "ch1" in ids
