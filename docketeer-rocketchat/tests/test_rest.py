"""Tests for timestamps, REST API methods, and status retries."""

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from docketeer.chat import RoomKind, RoomMessage
from docketeer_rocketchat.client import RocketChatClient, _parse_rc_timestamp


def test_parse_rc_timestamp_dict():
    ts = {"$date": 1_707_235_200_000}
    dt = _parse_rc_timestamp(ts)
    assert dt is not None
    assert dt.tzinfo == UTC
    assert dt.year == 2024


def test_parse_rc_timestamp_iso_string():
    dt = _parse_rc_timestamp("2026-02-06T10:00:00+00:00")
    assert dt is not None
    assert dt.year == 2026


def test_parse_rc_timestamp_invalid_string():
    assert _parse_rc_timestamp("not-a-date") is None


@pytest.mark.parametrize("value", [12345, None])
def test_parse_rc_timestamp_other_type(value: Any):
    assert _parse_rc_timestamp(value) is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://chat.example.com", "wss://chat.example.com/websocket"),
        ("http://chat.example.com", "ws://chat.example.com/websocket"),
        ("chat.example.com", "chat.example.com/websocket"),
    ],
)
def test_to_ws_url(url: str, expected: str):
    client = RocketChatClient()
    assert client._to_ws_url(url) == expected


@respx.mock
async def test_send_message(rc: RocketChatClient):
    respx.post("http://localhost:3000/api/v1/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await rc.send_message("room1", "hello")


@respx.mock
async def test_send_message_with_attachments(rc: RocketChatClient):
    route = respx.post("http://localhost:3000/api/v1/chat.postMessage")
    route.mock(return_value=httpx.Response(200, json={"success": True}))
    await rc.send_message("room1", "check", attachments=[{"color": "green"}])
    body = json.loads(route.calls[0].request.content)
    assert "attachments" in body


@respx.mock
async def test_upload_file(rc: RocketChatClient, tmp_path: Any):
    f = tmp_path / "test.txt"
    f.write_text("content")

    respx.post("http://localhost:3000/api/v1/rooms.media/room1").mock(
        return_value=httpx.Response(200, json={"file": {"_id": "file1"}})
    )
    respx.post("http://localhost:3000/api/v1/rooms.mediaConfirm/room1/file1").mock(
        return_value=httpx.Response(200, json={"success": True})
    )

    await rc.upload_file("room1", str(f), message="here it is")


@respx.mock
async def test_fetch_attachment_relative_url(rc: RocketChatClient):
    respx.get("http://localhost:3000/file-upload/abc.png").mock(
        return_value=httpx.Response(200, content=b"imagedata")
    )
    data = await rc.fetch_attachment("/file-upload/abc.png")
    assert data == b"imagedata"


@respx.mock
async def test_fetch_attachment_absolute_url(rc: RocketChatClient):
    respx.get("https://cdn.example.com/img.png").mock(
        return_value=httpx.Response(200, content=b"img")
    )
    data = await rc.fetch_attachment("https://cdn.example.com/img.png")
    assert data == b"img"


@respx.mock
async def test_fetch_message_success(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/chat.getMessage").mock(
        return_value=httpx.Response(
            200, json={"message": {"_id": "m1", "msg": "hello"}}
        )
    )
    msg = await rc.fetch_message("m1")
    assert msg is not None
    assert msg["msg"] == "hello"


@respx.mock
async def test_fetch_message_failure(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/chat.getMessage").mock(
        return_value=httpx.Response(500)
    )
    result = await rc.fetch_message("m1")
    assert result is None


@respx.mock
async def test_list_rooms(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ims": [
                    {"_id": "dm1", "usernames": ["testbot", "alice"]},
                    {"_id": "gdm1", "usernames": ["testbot", "alice", "bob"]},
                ]
            },
        )
    )
    respx.get("http://localhost:3000/api/v1/channels.list.joined").mock(
        return_value=httpx.Response(
            200,
            json={
                "channels": [
                    {
                        "_id": "ch1",
                        "name": "general",
                        "usernames": ["testbot", "alice"],
                    },
                ]
            },
        )
    )
    respx.get("http://localhost:3000/api/v1/groups.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "groups": [
                    {"_id": "grp1", "name": "secret", "usernames": ["testbot", "bob"]},
                ]
            },
        )
    )
    rooms = await rc.list_rooms()
    assert len(rooms) == 4
    by_id = {r.room_id: r for r in rooms}
    assert by_id["dm1"].kind is RoomKind.direct
    assert by_id["gdm1"].kind is RoomKind.group
    assert by_id["ch1"].kind is RoomKind.public
    assert by_id["ch1"].name == "general"
    assert by_id["grp1"].kind is RoomKind.private
    assert by_id["grp1"].name == "secret"
    # Room kinds cache should be populated
    assert rc._room_kinds["dm1"] is RoomKind.direct
    assert rc._room_kinds["ch1"] is RoomKind.public


@respx.mock
async def test_list_rooms_partial_failure(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(500)
    )
    respx.get("http://localhost:3000/api/v1/channels.list.joined").mock(
        return_value=httpx.Response(500)
    )
    respx.get("http://localhost:3000/api/v1/groups.list").mock(
        return_value=httpx.Response(
            200,
            json={"groups": [{"_id": "grp1", "name": "secret", "usernames": []}]},
        )
    )
    rooms = await rc.list_rooms()
    assert len(rooms) == 1
    assert rooms[0].kind is RoomKind.private


@respx.mock
async def test_list_rooms_all_fail(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(500)
    )
    respx.get("http://localhost:3000/api/v1/channels.list.joined").mock(
        return_value=httpx.Response(500)
    )
    respx.get("http://localhost:3000/api/v1/groups.list").mock(
        return_value=httpx.Response(500)
    )
    assert await rc.list_rooms() == []


@respx.mock
async def test_set_status_success(rc: RocketChatClient):
    respx.post("http://localhost:3000/api/v1/users.setStatus").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await rc.set_status("online")


@respx.mock
async def test_set_status_retry(rc: RocketChatClient):
    route = respx.post("http://localhost:3000/api/v1/users.setStatus")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, json={"success": True}),
    ]
    await rc.set_status("online")
    assert route.call_count == 2


@respx.mock
async def test_set_status_all_retries_fail(rc: RocketChatClient):
    respx.post("http://localhost:3000/api/v1/users.setStatus").mock(
        side_effect=httpx.HTTPError("fail")
    )
    with patch("docketeer_rocketchat.client.asyncio.sleep", new_callable=AsyncMock):
        await rc.set_status("online")


async def test_send_typing(rc: RocketChatClient):
    rc._ddp = AsyncMock()
    await rc.send_typing("room1", True)
    rc._ddp.call.assert_awaited_once_with(
        "stream-notify-room",
        ["room1/user-activity", rc.username, ["user-typing"], {}],
    )


async def test_send_typing_false(rc: RocketChatClient):
    rc._ddp = AsyncMock()
    await rc.send_typing("room1", False)
    rc._ddp.call.assert_awaited_once_with(
        "stream-notify-room", ["room1/user-activity", rc.username, [], {}]
    )


async def test_send_typing_no_ddp(rc: RocketChatClient):
    rc._ddp = None
    await rc.send_typing("room1", True)


async def test_send_typing_exception_swallowed(rc: RocketChatClient):
    rc._ddp = AsyncMock()
    rc._ddp.call.side_effect = Exception("connection lost")
    await rc.send_typing("room1", True)


# --- fetch_messages ---


@respx.mock
async def test_fetch_messages_by_count(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "_id": "m2",
                        "msg": "second",
                        "u": {"_id": "user1", "username": "alice", "name": "Alice"},
                        "ts": "2026-02-08T12:01:00+00:00",
                    },
                    {
                        "_id": "m1",
                        "msg": "first",
                        "u": {"_id": "user2", "username": "bob", "name": "Bob"},
                        "ts": "2026-02-08T12:00:00+00:00",
                    },
                ]
            },
        )
    )
    msgs = await rc.fetch_messages("room1", count=10)
    assert len(msgs) == 2
    assert isinstance(msgs[0], RoomMessage)
    assert msgs[0].message_id == "m1"
    assert msgs[0].username == "bob"
    assert msgs[0].display_name == "Bob"
    assert msgs[0].text == "first"
    assert msgs[1].message_id == "m2"


@respx.mock
async def test_fetch_messages_with_time_params(rc: RocketChatClient):
    route = respx.get("http://localhost:3000/api/v1/dm.history")
    route.mock(return_value=httpx.Response(200, json={"messages": []}))
    await rc.fetch_messages(
        "room1",
        after=datetime(2026, 2, 8, 10, 0, tzinfo=UTC),
        before=datetime(2026, 2, 8, 14, 0, tzinfo=UTC),
    )
    request = route.calls[0].request
    assert "oldest" in str(request.url)
    assert "latest" in str(request.url)


@respx.mock
async def test_fetch_messages_with_attachments(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "_id": "m1",
                        "msg": "check this",
                        "u": {"_id": "user1", "username": "alice", "name": "Alice"},
                        "ts": "2026-02-08T12:00:00+00:00",
                        "attachments": [
                            {
                                "image_url": "/file-upload/abc/pic.png",
                                "image_type": "image/png",
                                "title": "pic.png",
                            },
                        ],
                    },
                ]
            },
        )
    )
    msgs = await rc.fetch_messages("room1")
    assert len(msgs) == 1
    assert msgs[0].attachments is not None
    assert len(msgs[0].attachments) == 1
    assert msgs[0].attachments[0].url == "/file-upload/abc/pic.png"
    assert msgs[0].attachments[0].media_type == "image/png"
    assert msgs[0].attachments[0].title == "pic.png"


@respx.mock
async def test_fetch_messages_skips_system_messages(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "_id": "m1",
                        "msg": "joined",
                        "t": "uj",
                        "u": {"_id": "u1", "username": "alice"},
                    },
                    {
                        "_id": "m2",
                        "msg": "real message",
                        "u": {"_id": "u1", "username": "alice", "name": "Alice"},
                        "ts": "2026-02-08T12:00:00+00:00",
                    },
                ]
            },
        )
    )
    msgs = await rc.fetch_messages("room1")
    assert len(msgs) == 1
    assert msgs[0].text == "real message"


@respx.mock
async def test_fetch_messages_skips_no_timestamp(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "_id": "m1",
                        "msg": "no ts",
                        "u": {"_id": "user1", "username": "alice"},
                    },
                    {
                        "_id": "m2",
                        "msg": "has ts",
                        "u": {"_id": "user1", "username": "alice", "name": "Alice"},
                        "ts": "2026-02-08T12:00:00+00:00",
                    },
                ]
            },
        )
    )
    msgs = await rc.fetch_messages("room1")
    assert len(msgs) == 1
    assert msgs[0].text == "has ts"


@respx.mock
async def test_fetch_messages_skips_non_image_attachments(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "_id": "m1",
                        "msg": "check this",
                        "u": {"_id": "user1", "username": "alice", "name": "Alice"},
                        "ts": "2026-02-08T12:00:00+00:00",
                        "attachments": [
                            {"title": "some-file.pdf", "title_link": "/file.pdf"},
                        ],
                    },
                ]
            },
        )
    )
    msgs = await rc.fetch_messages("room1")
    assert len(msgs) == 1
    assert msgs[0].attachments == []


@respx.mock
async def test_fetch_messages_routes_to_channels_history(rc: RocketChatClient):
    rc._room_kinds["ch1"] = RoomKind.public
    route = respx.get("http://localhost:3000/api/v1/channels.history")
    route.mock(return_value=httpx.Response(200, json={"messages": []}))
    await rc.fetch_messages("ch1")
    assert route.called


@respx.mock
async def test_fetch_messages_routes_to_groups_history(rc: RocketChatClient):
    rc._room_kinds["grp1"] = RoomKind.private
    route = respx.get("http://localhost:3000/api/v1/groups.history")
    route.mock(return_value=httpx.Response(200, json={"messages": []}))
    await rc.fetch_messages("grp1")
    assert route.called


@respx.mock
async def test_fetch_messages_failure(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(500)
    )
    result = await rc.fetch_messages("room1")
    assert result == []


# --- react / unreact ---


@respx.mock
async def test_react(rc: RocketChatClient):
    route = respx.post("http://localhost:3000/api/v1/chat.react")
    route.mock(return_value=httpx.Response(200, json={"success": True}))
    await rc.react("msg1", ":thumbsup:")
    body = json.loads(route.calls[0].request.content)
    assert body["messageId"] == "msg1"
    assert body["emoji"] == ":thumbsup:"
    assert body["shouldReact"] is True


@respx.mock
async def test_unreact(rc: RocketChatClient):
    route = respx.post("http://localhost:3000/api/v1/chat.react")
    route.mock(return_value=httpx.Response(200, json={"success": True}))
    await rc.unreact("msg1", ":thumbsup:")
    body = json.loads(route.calls[0].request.content)
    assert body["messageId"] == "msg1"
    assert body["emoji"] == ":thumbsup:"
    assert body["shouldReact"] is False
