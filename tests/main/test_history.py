"""Tests for history loading and timestamp formatting."""

from docketeer.brain import Brain
from docketeer.main import (
    _format_timestamp,
    fetch_history_for_brain,
    load_all_history,
)
from docketeer.testing import MemoryChat


async def test_load_all_history(chat: MemoryChat, brain: Brain):
    chat._dm_rooms = [
        {"_id": "r1", "usernames": ["testbot", "alice"]},
        {"_id": "r2", "usernames": ["testbot", "bob"]},
    ]
    chat._room_history = {
        "r1": [
            {
                "msg": "hi",
                "u": {"_id": "user1", "username": "alice"},
                "ts": "2026-02-06T10:00:00Z",
            }
        ],
        "r2": [
            {
                "msg": "hey",
                "u": {"_id": "user2", "username": "bob"},
                "ts": "2026-02-06T11:00:00Z",
            }
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


def test_format_timestamp():
    result = _format_timestamp({"$date": 1_707_235_200_000})
    assert result != ""
    assert "2024" in result


def test_format_timestamp_none():
    assert _format_timestamp(None) == ""


async def test_fetch_history_for_brain(chat: MemoryChat):
    chat._room_history = {
        "r1": [
            {
                "msg": "hello",
                "u": {"_id": "user1", "username": "alice"},
                "ts": "2026-02-06T10:00:00Z",
            },
            {
                "msg": "hi back",
                "u": {"_id": "bot123", "username": "testbot"},
                "ts": "2026-02-06T10:01:00Z",
            },
        ]
    }
    msgs = await fetch_history_for_brain(chat, "r1")
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"


async def test_fetch_history_for_brain_skips_system(chat: MemoryChat):
    chat._room_history = {
        "r1": [
            {"msg": "", "t": "uj", "u": {"_id": "u1", "username": "alice"}},
            {
                "msg": "real",
                "u": {"_id": "user1", "username": "alice"},
                "ts": "2026-02-06T10:00:00Z",
            },
        ]
    }
    msgs = await fetch_history_for_brain(chat, "r1")
    assert len(msgs) == 1


async def test_fetch_history_for_brain_skips_empty(chat: MemoryChat):
    chat._room_history = {
        "r1": [
            {"msg": "", "u": {"_id": "user1", "username": "alice"}},
        ]
    }
    msgs = await fetch_history_for_brain(chat, "r1")
    assert len(msgs) == 0
