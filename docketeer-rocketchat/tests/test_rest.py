"""Tests for timestamps, REST API methods, and status retries."""

import json
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

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
async def test_fetch_room_history(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={"messages": [{"msg": "third"}, {"msg": "second"}, {"msg": "first"}]},
        )
    )
    result = await rc.fetch_room_history("room1")
    assert result[0]["msg"] == "first"
    assert result[-1]["msg"] == "third"


@respx.mock
async def test_fetch_room_history_failure(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(500)
    )
    assert await rc.fetch_room_history("room1") == []


@respx.mock
async def test_fetch_history_as_messages(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "msg": "hi back",
                        "u": {"_id": "bot_uid", "username": "testbot"},
                        "ts": "2026-02-06T10:01:00+00:00",
                    },
                    {
                        "msg": "hello",
                        "u": {"_id": "user1", "username": "alice"},
                        "ts": "2026-02-06T10:00:00+00:00",
                    },
                ]
            },
        )
    )
    msgs = await rc.fetch_history_as_messages("room1")
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[0].username == "alice"
    assert msgs[1].role == "assistant"
    assert msgs[1].username == "testbot"
    assert msgs[0].timestamp != ""


@respx.mock
async def test_fetch_history_as_messages_skips_system_and_empty(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {"msg": "", "t": "uj", "u": {"_id": "u1", "username": "alice"}},
                    {"msg": "", "u": {"_id": "u1", "username": "alice"}},
                    {
                        "msg": "real",
                        "u": {"_id": "user1", "username": "alice"},
                        "ts": "2026-02-06T10:00:00+00:00",
                    },
                ]
            },
        )
    )
    msgs = await rc.fetch_history_as_messages("room1")
    assert len(msgs) == 1
    assert msgs[0].text == "real"


@respx.mock
async def test_fetch_history_as_messages_no_timestamp(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {"msg": "no ts", "u": {"_id": "user1", "username": "alice"}},
                ]
            },
        )
    )
    msgs = await rc.fetch_history_as_messages("room1")
    assert len(msgs) == 1
    assert msgs[0].timestamp == ""


@respx.mock
async def test_list_dm_rooms(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(200, json={"ims": [{"_id": "r1"}, {"_id": "r2"}]})
    )
    rooms = await rc.list_dm_rooms()
    assert len(rooms) == 2


@respx.mock
async def test_list_dm_rooms_failure(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.list").mock(
        return_value=httpx.Response(500)
    )
    assert await rc.list_dm_rooms() == []


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
