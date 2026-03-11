from docketeer.chat import IncomingMessage, IncomingReaction, RoomInfo, RoomKind
from docketeer_slack.client import SlackClient


async def test_parse_socket_event_app_mention(slack_client: SlackClient):
    event = {
        "payload": {
            "event": {
                "type": "app_mention",
                "channel": "C1",
                "user": "U1",
                "text": "<@U_BOT> hi",
                "ts": "1718123456.123456",
            }
        }
    }
    msg = await slack_client._parse_socket_event(event)
    assert isinstance(msg, IncomingMessage)
    assert msg.message_id == "C1:1718123456.123456"
    assert msg.room_id == "C1"
    assert msg.kind is RoomKind.public


async def test_parse_socket_event_dm(slack_client: SlackClient):
    event = {
        "payload": {
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "hello",
                "ts": "1718123456.123456",
            }
        }
    }
    msg = await slack_client._parse_socket_event(event)
    assert isinstance(msg, IncomingMessage)
    assert msg.kind is RoomKind.direct
    assert msg.message_id == "D1:1718123456.123456"


async def test_parse_socket_event_channel_without_mention_ignored(
    slack_client: SlackClient,
):
    event = {
        "payload": {
            "event": {
                "type": "message",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "hello",
                "ts": "1718123456.123456",
            }
        }
    }
    assert await slack_client._parse_socket_event(event) is None


async def test_parse_socket_event_channel_mention_allowed(slack_client: SlackClient):
    event = {
        "payload": {
            "event": {
                "type": "message",
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "text": "<@U_BOT> hello",
                "ts": "1718123456.123456",
            }
        }
    }
    msg = await slack_client._parse_socket_event(event)
    assert isinstance(msg, IncomingMessage)
    assert msg.kind is RoomKind.public


async def test_parse_socket_event_thread(slack_client: SlackClient):
    event = {
        "payload": {
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U1",
                "text": "reply",
                "ts": "1718123457.123456",
                "thread_ts": "1718123456.123456",
            }
        }
    }
    msg = await slack_client._parse_socket_event(event)
    assert isinstance(msg, IncomingMessage)
    assert msg.thread_id == "1718123456.123456"


async def test_parse_socket_event_own_message(slack_client: SlackClient):
    event = {
        "payload": {
            "event": {
                "type": "message",
                "channel_type": "im",
                "channel": "D1",
                "user": "U_BOT",
                "text": "my own",
                "ts": "1718123456.123456",
            }
        }
    }
    msg = await slack_client._parse_socket_event(event)
    assert isinstance(msg, IncomingMessage)
    assert msg.is_own is True


async def test_parse_socket_event_reaction_added(slack_client: SlackClient):
    event = {
        "payload": {
            "event": {
                "type": "reaction_added",
                "user": "U1",
                "reaction": "thumbsup",
                "item": {
                    "type": "message",
                    "channel": "D1",
                    "ts": "1718123456.123456",
                },
                "event_ts": "1718123457.000000",
            }
        }
    }
    result = await slack_client._parse_socket_event(event)
    assert isinstance(result, IncomingReaction)
    assert result.emoji == ":thumbsup:"


async def test_parse_socket_event_reaction_uses_known_room_kind(
    slack_client: SlackClient,
):
    slack_client._rooms["C1"] = RoomInfo(
        room_id="C1", kind=RoomKind.public, members=[], name="general"
    )
    event = {
        "payload": {
            "event": {
                "type": "reaction_added",
                "user": "U1",
                "reaction": "thumbsup",
                "item": {
                    "type": "message",
                    "channel": "C1",
                    "ts": "1718123456.123456",
                },
                "event_ts": "1718123457.000000",
            }
        }
    }
    result = await slack_client._parse_socket_event(event)
    assert isinstance(result, IncomingReaction)
    assert result.kind is RoomKind.public
