"""Tests for history loading."""

from datetime import UTC, datetime

from docketeer.brain import Brain
from docketeer.chat import RoomMessage
from docketeer.main import load_all_history
from docketeer.testing import MemoryChat


async def test_load_all_history(chat: MemoryChat, brain: Brain):
    chat._dm_rooms = [
        {"_id": "r1", "usernames": ["testbot", "alice"]},
        {"_id": "r2", "usernames": ["testbot", "bob"]},
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
    assert brain._room_info["r1"].is_direct is True
    assert brain._room_info["r1"].members == ["testbot", "alice"]
    assert brain._room_info["r2"].members == ["testbot", "bob"]


async def test_load_all_history_skips_no_id(chat: MemoryChat, brain: Brain):
    chat._dm_rooms = [{"usernames": ["testbot", "alice"]}]
    await load_all_history(chat, brain)
