from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from docketeer.chat import RoomInfo, RoomKind
from docketeer_slack.client import SlackClient


async def test_open_socket(slack_client: SlackClient):
    with (
        patch.object(slack_client, "_socket_url", AsyncMock(return_value="wss://example.test/socket")),
        patch("docketeer_slack.client.websockets.connect", AsyncMock(return_value="ws")) as connect,
    ):
        await slack_client._open_socket()
    connect.assert_awaited_once_with("wss://example.test/socket", open_timeout=30)
    assert slack_client._ws == "ws"


async def test_parse_socket_event_non_message(slack_client: SlackClient):
    assert await slack_client._parse_socket_event({"payload": {"event": {"type": "other"}}}) is None


async def test_parse_socket_event_private_allowlist(slack_client: SlackClient):
    slack_client._allowlist = {"G1"}
    event = {
        "payload": {
            "event": {
                "type": "message",
                "channel_type": "group",
                "channel": "G1",
                "user": "U1",
                "text": "hello",
                "ts": "1718123456.123456",
            }
        }
    }
    msg = await slack_client._parse_socket_event(event)
    assert msg is not None
    assert msg.kind is RoomKind.private


async def test_incoming_from_message_invalid(slack_client: SlackClient):
    assert slack_client._incoming_from_message({"user": "U1"}, kind=RoomKind.direct) is None
    assert (
        slack_client._incoming_from_message(
            {"channel": "D1", "ts": "1718123456.123456", "user": "U1"},
            kind=RoomKind.direct,
        )
        is None
    )


async def test_incoming_from_message_ignores_subtype(slack_client: SlackClient):
    message = {
        "channel": "D1",
        "user": "U1",
        "text": "ignored",
        "ts": "1718123456.123456",
        "subtype": "bot_message",
    }
    assert slack_client._incoming_from_message(message, kind=RoomKind.direct) is None


@respx.mock
async def test_fetch_messages_skips_invalid_and_ignored(slack_client: SlackClient):
    respx.get("https://slack.com/api/conversations.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    {"ts": "bad", "user": "U1", "text": "bad ts"},
                    {
                        "ts": "1718123457.123456",
                        "user": "U1",
                        "text": "bot",
                        "subtype": "bot_message",
                    },
                    {"ts": "1718123458.123456", "user": "U2", "text": "ok"},
                ],
            },
        )
    )
    messages = await slack_client.fetch_messages("C1")
    assert [m.text for m in messages] == ["ok"]


@respx.mock
async def test_list_rooms_paginates(slack_client: SlackClient):
    route = respx.get("https://slack.com/api/conversations.list")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [{"id": "C1", "name": "one"}],
                "response_metadata": {"next_cursor": "NEXT"},
            },
        ),
        httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [{"id": "C2", "name": "two"}],
                "response_metadata": {"next_cursor": ""},
            },
        ),
    ]
    rooms = await slack_client.list_rooms()
    assert [r.room_id for r in rooms] == ["C1", "C2"]


async def test_room_context_cached_private(slack_client: SlackClient):
    slack_client._rooms["G1"] = RoomInfo(room_id="G1", kind=RoomKind.private, members=[], name="secret")
    assert await slack_client.room_context("G1", "alice") == "Room: #secret (private)"


async def test_room_context_cached_unknown_name(slack_client: SlackClient):
    slack_client._rooms["C1"] = RoomInfo(room_id="C1", kind=RoomKind.public, members=[], name="")
    assert await slack_client.room_context("C1", "alice") == "Room: #C1 (public)"


async def test_fetch_message_invalid_id(slack_client: SlackClient):
    with pytest.raises(ValueError):
        await slack_client.fetch_message("bad")
