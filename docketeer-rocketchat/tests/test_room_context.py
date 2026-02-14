"""Tests for room context rendering via the Rocket Chat API."""

from unittest.mock import AsyncMock, patch

import httpx
import respx

from docketeer.chat import RoomKind
from docketeer_rocketchat.client import RocketChatClient
from docketeer_rocketchat.room_context import (
    build_room_context,
    fallback_room_context,
)


@respx.mock
async def test_room_context_dm(rc: RocketChatClient):
    rc._room_kinds["dm1"] = RoomKind.direct
    respx.get("http://localhost:3000/api/v1/users.info").mock(
        return_value=httpx.Response(
            200,
            json={
                "user": {"name": "Alice Smith", "username": "alice", "status": "online"}
            },
        )
    )
    ctx = await rc.room_context("dm1", "alice")
    assert "Alice Smith" in ctx
    assert "@alice" in ctx
    assert "online" in ctx


@respx.mock
async def test_room_context_dm_api_failure(rc: RocketChatClient):
    rc._room_kinds["dm1"] = RoomKind.direct
    respx.get("http://localhost:3000/api/v1/users.info").mock(
        return_value=httpx.Response(500)
    )
    ctx = await rc.room_context("dm1", "alice")
    assert ctx == "Room: DM with @alice"


@respx.mock
async def test_room_context_group_dm(rc: RocketChatClient):
    rc._room_kinds["gdm1"] = RoomKind.group
    respx.get("http://localhost:3000/api/v1/dm.members").mock(
        return_value=httpx.Response(
            200,
            json={
                "members": [
                    {"username": "testbot", "name": "Test Bot", "status": "online"},
                    {"username": "alice", "name": "Alice", "status": "online"},
                    {"username": "bob", "name": "Bob", "status": "away"},
                ]
            },
        )
    )
    ctx = await rc.room_context("gdm1", "alice")
    assert "group DM" in ctx
    assert "Alice" in ctx
    assert "Bob" in ctx


@respx.mock
async def test_room_context_channel(rc: RocketChatClient):
    rc._room_kinds["ch1"] = RoomKind.public
    respx.get("http://localhost:3000/api/v1/channels.info").mock(
        return_value=httpx.Response(
            200,
            json={
                "channel": {
                    "name": "general",
                    "topic": "General discussion",
                    "description": "The main channel",
                    "usersCount": 10,
                }
            },
        )
    )
    respx.get("http://localhost:3000/api/v1/channels.members").mock(
        return_value=httpx.Response(
            200,
            json={
                "members": [
                    {"username": "alice", "name": "Alice", "status": "online"},
                    {"username": "bob", "name": "Bob", "status": "offline"},
                ]
            },
        )
    )
    ctx = await rc.room_context("ch1", "alice")
    assert "#general" in ctx
    assert "public" in ctx
    assert "10 members" in ctx
    assert "General discussion" in ctx
    assert "The main channel" in ctx
    assert "Alice (@alice)" in ctx
    assert "Bob" not in ctx.split("Online:")[-1] or "bob" not in ctx  # bob is offline


@respx.mock
async def test_room_context_private_channel(rc: RocketChatClient):
    rc._room_kinds["grp1"] = RoomKind.private
    respx.get("http://localhost:3000/api/v1/groups.info").mock(
        return_value=httpx.Response(
            200,
            json={
                "group": {
                    "name": "secret",
                    "topic": "",
                    "description": "",
                    "usersCount": 3,
                }
            },
        )
    )
    respx.get("http://localhost:3000/api/v1/groups.members").mock(
        return_value=httpx.Response(
            200,
            json={"members": []},
        )
    )
    ctx = await rc.room_context("grp1", "bob")
    assert "#secret" in ctx
    assert "private" in ctx
    assert "3 members" in ctx


@respx.mock
async def test_room_context_unknown_kind(rc: RocketChatClient):
    ctx = await rc.room_context("unknown_room", "alice")
    assert ctx == "Room: DM with @alice"


@respx.mock
async def test_room_context_dm_fallback_on_exception(rc: RocketChatClient):
    """DM context falls back when the users.info API fails with a network error."""
    rc._room_kinds["dm1"] = RoomKind.direct
    respx.get("http://localhost:3000/api/v1/users.info").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    ctx = await rc.room_context("dm1", "alice")
    assert ctx == "Room: DM with @alice"


@respx.mock
async def test_room_context_group_dm_fallback(rc: RocketChatClient):
    """Group DM context falls back when dm.members API fails."""
    rc._room_kinds["gdm1"] = RoomKind.group
    respx.get("http://localhost:3000/api/v1/dm.members").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    ctx = await rc.room_context("gdm1", "alice")
    assert ctx == "Room: group DM with @alice"


@respx.mock
async def test_room_context_channel_members_failure(rc: RocketChatClient):
    """Channel context omits online members when the members API fails."""
    rc._room_kinds["ch1"] = RoomKind.public
    respx.get("http://localhost:3000/api/v1/channels.info").mock(
        return_value=httpx.Response(
            200,
            json={
                "channel": {
                    "name": "general",
                    "topic": "",
                    "description": "",
                    "usersCount": 5,
                }
            },
        )
    )
    respx.get("http://localhost:3000/api/v1/channels.members").mock(
        side_effect=httpx.ConnectError("refused")
    )
    ctx = await rc.room_context("ch1", "alice")
    assert "#general" in ctx
    assert "Online:" not in ctx


async def test_build_raises_uses_fallback():
    """When _build raises unexpectedly, fallback is used."""
    with patch(
        "docketeer_rocketchat.room_context._build",
        AsyncMock(side_effect=RuntimeError("unexpected")),
    ):
        ctx = await build_room_context(
            AsyncMock(), "bot", "dm1", "alice", RoomKind.direct
        )
    assert ctx == "Room: DM with @alice"


async def test_fallback_room_context_direct():
    ctx = fallback_room_context("r1", "alice", RoomKind.direct)
    assert ctx == "Room: DM with @alice"


async def test_fallback_room_context_group():
    ctx = fallback_room_context("r1", "alice", RoomKind.group)
    assert ctx == "Room: group DM with @alice"


async def test_fallback_room_context_unknown():
    ctx = fallback_room_context("r1", "alice", None)
    assert ctx == ""
