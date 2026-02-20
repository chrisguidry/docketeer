"""Tests for incoming_messages, _parse_message_event, and reconnect."""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import respx

from docketeer_rocketchat.client import RocketChatClient


def _make_event(
    msg_id: str, text: str, user_id: str = "user1", username: str = "alice"
) -> dict[str, Any]:
    return {
        "msg": "changed",
        "fields": {
            "args": [
                {
                    "_id": msg_id,
                    "msg": text,
                    "rid": "r1",
                    "u": {"_id": user_id, "username": username},
                }
            ]
        },
    }


async def test_incoming_messages_filters():
    """Own messages, empty text, and unparsable events are skipped."""
    client = RocketChatClient()
    client._user_id = "bot_uid"

    ddp = AsyncMock()
    events = [
        _make_event("m1", "my own", user_id="bot_uid", username="bot"),
        _make_event("m2", "", user_id="user1"),
        {"msg": "added"},
        _make_event("m3", "hello"),
    ]

    async def fake_events() -> AsyncGenerator[
        dict[str, Any], None
    ]:  # pragma: no branch
        for e in events:  # pragma: no branch
            yield e

    ddp.events = fake_events
    client._ddp = ddp

    results = []
    with patch.object(client, "_after_connect", new_callable=AsyncMock):
        async for msg in client.incoming_messages():  # pragma: no branch
            results.append(msg)
            break
    assert len(results) == 1
    assert results[0].text == "hello"


async def test_incoming_messages_dedup():
    """Duplicate message IDs are skipped."""
    client = RocketChatClient()
    client._user_id = "bot_uid"

    ddp = AsyncMock()
    events = [
        _make_event("m1", "hello"),
        _make_event("m1", "hello again"),
        _make_event("m2", "world"),
    ]

    async def fake_events() -> AsyncGenerator[
        dict[str, Any], None
    ]:  # pragma: no branch
        for e in events:  # pragma: no branch
            yield e

    ddp.events = fake_events
    client._ddp = ddp

    results = []
    with patch.object(client, "_after_connect", new_callable=AsyncMock):
        async for msg in client.incoming_messages():  # pragma: no branch
            results.append(msg)
            if len(results) == 2:
                break
    assert len(results) == 2
    assert results[0].text == "hello"
    assert results[1].text == "world"


async def test_incoming_messages_no_ddp():
    """No DDP connection means immediate return."""
    client = RocketChatClient()
    client._ddp = None
    results = []
    async for msg in client.incoming_messages():  # pragma: no branch - never iterates
        results.append(msg)  # pragma: no cover - no messages
    assert results == []


async def test_parse_message_event_changed(rc: RocketChatClient):
    event = {
        "msg": "changed",
        "fields": {
            "args": [
                {
                    "_id": "m1",
                    "msg": "hi",
                    "rid": "r1",
                    "u": {"_id": "u1", "username": "alice", "name": "Alice"},
                    "ts": "2026-02-06T10:00:00Z",
                }
            ]
        },
    }
    msg = await rc._parse_message_event(event)
    assert msg is not None
    assert msg.text == "hi"
    assert msg.username == "alice"
    assert msg.display_name == "Alice"


async def test_parse_message_event_not_changed(rc: RocketChatClient):
    assert await rc._parse_message_event({"msg": "added"}) is None


async def test_parse_message_event_no_args(rc: RocketChatClient):
    event = {"msg": "changed", "fields": {"args": []}}
    assert await rc._parse_message_event(event) is None


async def test_parse_message_event_non_dict_args(rc: RocketChatClient):
    event = {"msg": "changed", "fields": {"args": ["not a dict"]}}
    assert await rc._parse_message_event(event) is None


async def test_parse_message_event_system_message(rc: RocketChatClient):
    event = {
        "msg": "changed",
        "fields": {"args": [{"_id": "m1", "t": "uj", "rid": "r1", "u": {"_id": "u1"}}]},
    }
    assert await rc._parse_message_event(event) is None


@respx.mock
async def test_parse_message_event_with_payload_fetch(rc: RocketChatClient):
    respx.get("http://localhost:3000/api/v1/chat.getMessage").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "_id": "m1",
                    "msg": "full message",
                    "rid": "r1",
                    "u": {"_id": "u1", "username": "alice", "name": "Alice"},
                }
            },
        )
    )
    event = {
        "msg": "changed",
        "fields": {
            "args": [
                {
                    "payload": {
                        "_id": "m1",
                        "rid": "r1",
                        "sender": {"_id": "u1", "username": "alice"},
                    },
                }
            ]
        },
    }
    msg = await rc._parse_message_event(event)
    assert msg is not None
    assert msg.text == "full message"


@respx.mock
async def test_parse_message_event_payload_fetch_returns_none(rc: RocketChatClient):
    """When fetch_message returns None, fall back to payload data."""
    respx.get("http://localhost:3000/api/v1/chat.getMessage").mock(
        return_value=httpx.Response(500)
    )
    event = {
        "msg": "changed",
        "fields": {
            "args": [
                {
                    "payload": {
                        "_id": "m1",
                        "rid": "r1",
                        "sender": {"_id": "u1", "username": "alice"},
                    },
                }
            ]
        },
    }
    msg = await rc._parse_message_event(event)
    assert msg is not None
    assert msg.username == "alice"
    assert msg.room_id == "r1"


async def test_parse_message_event_attachment_without_image_url(rc: RocketChatClient):
    """Attachments without image_url are skipped."""
    event = {
        "msg": "changed",
        "fields": {
            "args": [
                {
                    "_id": "m1",
                    "msg": "look",
                    "rid": "r1",
                    "u": {"_id": "u1", "username": "alice"},
                    "attachments": [
                        {"title": "file.txt", "type": "application/text"},
                    ],
                }
            ]
        },
    }
    msg = await rc._parse_message_event(event)
    assert msg is not None
    assert msg.attachments == []


async def test_parse_message_event_with_attachments(rc: RocketChatClient):
    event = {
        "msg": "changed",
        "fields": {
            "args": [
                {
                    "_id": "m1",
                    "msg": "look",
                    "rid": "r1",
                    "u": {"_id": "u1", "username": "alice"},
                    "attachments": [
                        {
                            "image_url": "/uploads/pic.png",
                            "image_type": "image/png",
                            "title": "pic.png",
                        }
                    ],
                }
            ]
        },
    }
    msg = await rc._parse_message_event(event)
    assert msg is not None
    assert msg.attachments is not None
    assert len(msg.attachments) == 1
    assert msg.attachments[0].url == "/uploads/pic.png"
