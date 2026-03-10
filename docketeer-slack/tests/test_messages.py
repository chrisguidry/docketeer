from docketeer.chat import RoomKind
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
    assert msg is not None
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
    assert msg is not None
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
    assert msg is not None
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
    assert msg is not None
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
    assert msg is not None
    assert msg.is_own is True
