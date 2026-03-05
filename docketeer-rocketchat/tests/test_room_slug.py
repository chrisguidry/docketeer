"""Tests for room_slug() in the Rocket Chat client."""

import httpx
import respx

from docketeer.chat import RoomKind
from docketeer_rocketchat.client import RocketChatClient


@respx.mock
async def test_room_slug_dm(rc: RocketChatClient):
    rc._room_kinds["dm1"] = RoomKind.direct
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ims": [
                    {"_id": "dm1", "usernames": ["testbot", "alice"]},
                ]
            },
        )
    )
    respx.get("http://localhost:3000/api/v1/channels.list.joined").mock(
        return_value=httpx.Response(200, json={"channels": []})
    )
    respx.get("http://localhost:3000/api/v1/groups.list").mock(
        return_value=httpx.Response(200, json={"groups": []})
    )
    slug = await rc.room_slug("dm1")
    assert slug == "alice"


@respx.mock
async def test_room_slug_channel(rc: RocketChatClient):
    rc._room_kinds["ch1"] = RoomKind.public
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(200, json={"ims": []})
    )
    respx.get("http://localhost:3000/api/v1/channels.list.joined").mock(
        return_value=httpx.Response(
            200,
            json={
                "channels": [
                    {"_id": "ch1", "name": "general", "usernames": []},
                ]
            },
        )
    )
    respx.get("http://localhost:3000/api/v1/groups.list").mock(
        return_value=httpx.Response(200, json={"groups": []})
    )
    slug = await rc.room_slug("ch1")
    assert slug == "general"


@respx.mock
async def test_room_slug_dm_not_in_list(rc: RocketChatClient):
    rc._room_kinds["dm1"] = RoomKind.direct
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(
            200,
            json={"ims": [{"_id": "other", "usernames": ["testbot", "bob"]}]},
        )
    )
    respx.get("http://localhost:3000/api/v1/channels.list.joined").mock(
        return_value=httpx.Response(200, json={"channels": []})
    )
    respx.get("http://localhost:3000/api/v1/groups.list").mock(
        return_value=httpx.Response(200, json={"groups": []})
    )
    slug = await rc.room_slug("dm1")
    assert slug == "dm1"


@respx.mock
async def test_room_slug_dm_no_other_members(rc: RocketChatClient):
    rc._room_kinds["dm1"] = RoomKind.direct
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(
            200,
            json={"ims": [{"_id": "dm1", "usernames": ["testbot"]}]},
        )
    )
    respx.get("http://localhost:3000/api/v1/channels.list.joined").mock(
        return_value=httpx.Response(200, json={"channels": []})
    )
    respx.get("http://localhost:3000/api/v1/groups.list").mock(
        return_value=httpx.Response(200, json={"groups": []})
    )
    slug = await rc.room_slug("dm1")
    assert slug == "dm1"


@respx.mock
async def test_room_slug_channel_no_name(rc: RocketChatClient):
    rc._room_kinds["ch1"] = RoomKind.public
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(200, json={"ims": []})
    )
    respx.get("http://localhost:3000/api/v1/channels.list.joined").mock(
        return_value=httpx.Response(
            200,
            json={"channels": [{"_id": "ch1", "name": "", "usernames": []}]},
        )
    )
    respx.get("http://localhost:3000/api/v1/groups.list").mock(
        return_value=httpx.Response(200, json={"groups": []})
    )
    slug = await rc.room_slug("ch1")
    assert slug == "ch1"


async def test_room_slug_unknown(rc: RocketChatClient):
    slug = await rc.room_slug("unknown_room")
    assert slug == "unknown_room"
