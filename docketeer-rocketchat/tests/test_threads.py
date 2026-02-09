"""Tests for thread support in the Rocket.Chat client."""

import json
from pathlib import Path

import httpx
import respx

from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext, registry
from docketeer_rocketchat import register_tools
from docketeer_rocketchat.client import RocketChatClient

# --- Incoming messages: tmid extraction ---


async def test_parse_message_event_extracts_tmid(rc: RocketChatClient):
    event = {
        "msg": "changed",
        "fields": {
            "args": [
                {
                    "_id": "m1",
                    "msg": "thread reply",
                    "rid": "r1",
                    "tmid": "parent_msg_1",
                    "u": {"_id": "u1", "username": "alice", "name": "Alice"},
                    "ts": "2026-02-09T12:00:00Z",
                }
            ]
        },
    }
    msg = await rc._parse_message_event(event)
    assert msg is not None
    assert msg.thread_id == "parent_msg_1"


async def test_parse_message_event_no_tmid(rc: RocketChatClient):
    event = {
        "msg": "changed",
        "fields": {
            "args": [
                {
                    "_id": "m1",
                    "msg": "channel message",
                    "rid": "r1",
                    "u": {"_id": "u1", "username": "alice", "name": "Alice"},
                    "ts": "2026-02-09T12:00:00Z",
                }
            ]
        },
    }
    msg = await rc._parse_message_event(event)
    assert msg is not None
    assert msg.thread_id == ""


# --- send_message: tmid in POST body ---


@respx.mock
async def test_send_message_with_thread_id(rc: RocketChatClient):
    route = respx.post("http://localhost:3000/api/v1/chat.postMessage")
    route.mock(return_value=httpx.Response(200, json={"success": True}))
    await rc.send_message("room1", "reply", thread_id="parent_1")
    body = json.loads(route.calls[0].request.content)
    assert body["tmid"] == "parent_1"


@respx.mock
async def test_send_message_without_thread_id(rc: RocketChatClient):
    route = respx.post("http://localhost:3000/api/v1/chat.postMessage")
    route.mock(return_value=httpx.Response(200, json={"success": True}))
    await rc.send_message("room1", "hello")
    body = json.loads(route.calls[0].request.content)
    assert "tmid" not in body


# --- upload_file: tmid in media confirm ---


@respx.mock
async def test_upload_file_with_thread_id(rc: RocketChatClient, tmp_path: Path):
    f = tmp_path / "test.txt"
    f.write_text("content")

    respx.post("http://localhost:3000/api/v1/rooms.media/room1").mock(
        return_value=httpx.Response(200, json={"file": {"_id": "file1"}})
    )
    confirm_route = respx.post(
        "http://localhost:3000/api/v1/rooms.mediaConfirm/room1/file1"
    )
    confirm_route.mock(return_value=httpx.Response(200, json={"success": True}))

    await rc.upload_file("room1", str(f), message="here", thread_id="parent_1")
    body = json.loads(confirm_route.calls[0].request.content)
    assert body["tmid"] == "parent_1"


@respx.mock
async def test_upload_file_without_thread_id(rc: RocketChatClient, tmp_path: Path):
    f = tmp_path / "test.txt"
    f.write_text("content")

    respx.post("http://localhost:3000/api/v1/rooms.media/room1").mock(
        return_value=httpx.Response(200, json={"file": {"_id": "file1"}})
    )
    confirm_route = respx.post(
        "http://localhost:3000/api/v1/rooms.mediaConfirm/room1/file1"
    )
    confirm_route.mock(return_value=httpx.Response(200, json={"success": True}))

    await rc.upload_file("room1", str(f), message="here")
    body = json.loads(confirm_route.calls[0].request.content)
    assert "tmid" not in body


# --- fetch_messages: tmid on RoomMessage ---


@respx.mock
async def test_fetch_messages_extracts_tmid(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "_id": "m1",
                        "msg": "thread reply",
                        "tmid": "parent_1",
                        "u": {"_id": "u1", "username": "alice", "name": "Alice"},
                        "ts": "2026-02-09T12:00:00+00:00",
                    },
                ]
            },
        )
    )
    msgs = await rc.fetch_messages("room1")
    assert len(msgs) == 1
    assert msgs[0].thread_id == "parent_1"


@respx.mock
async def test_fetch_messages_no_tmid(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/dm.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "_id": "m1",
                        "msg": "channel message",
                        "u": {"_id": "u1", "username": "alice", "name": "Alice"},
                        "ts": "2026-02-09T12:00:00+00:00",
                    },
                ]
            },
        )
    )
    msgs = await rc.fetch_messages("room1")
    assert len(msgs) == 1
    assert msgs[0].thread_id == ""


# --- send_file tool: thread_id passthrough ---


async def test_send_file_passes_thread_id(tool_context: ToolContext):
    chat = MemoryChat()
    (tool_context.workspace / "test.txt").write_text("hello")
    tool_context.thread_id = "t1"
    register_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "test.txt"}, tool_context)
    assert "Sent" in result
    assert chat.uploaded_files[0].thread_id == "t1"
