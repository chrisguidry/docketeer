"""Tests for history loading."""

from docketeer.brain import Brain
from docketeer.chat import ChatClient
from docketeer.main import load_all_history
from docketeer.prompt import HistoryMessage
from docketeer.testing import MemoryChat


async def test_load_all_history(chat: MemoryChat, brain: Brain):
    chat._dm_rooms = [
        {"_id": "r1", "usernames": ["testbot", "alice"]},
        {"_id": "r2", "usernames": ["testbot", "bob"]},
    ]
    chat._history_messages = {
        "r1": [
            HistoryMessage(
                role="user", username="alice", text="hi", timestamp="2026-02-06 10:00"
            )
        ],
        "r2": [
            HistoryMessage(
                role="user", username="bob", text="hey", timestamp="2026-02-06 11:00"
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


async def test_base_fetch_history_as_messages_returns_empty():
    result = await ChatClient.fetch_history_as_messages(MemoryChat(), "room1")
    assert result == []
