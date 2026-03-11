from docketeer.chat import IncomingMessage, RoomKind
from docketeer_slack.client import SlackClient


def _msg(
    *,
    kind: RoomKind = RoomKind.direct,
    thread_id: str = "",
    channel: str = "D1",
    ts: str = "1718123456.123456",
) -> IncomingMessage:
    return IncomingMessage(
        message_id=f"{channel}:{ts}",
        user_id="U1",
        username="U1",
        display_name="U1",
        text="hello",
        room_id=channel,
        kind=kind,
        thread_id=thread_id,
    )


async def test_reply_thread_id_no_thread(slack_client: SlackClient):
    """Without an existing thread, reply inline (no forced threading)."""
    result = await slack_client.reply_thread_id(_msg(kind=RoomKind.direct))
    assert result == ""


async def test_reply_thread_id_existing_thread(slack_client: SlackClient):
    """If already in a thread, stay in it."""
    result = await slack_client.reply_thread_id(
        _msg(kind=RoomKind.direct, thread_id="1718123400.000000")
    )
    assert result == "1718123400.000000"


async def test_reply_thread_id_channel_no_thread(slack_client: SlackClient):
    """Channels also don't force threading — the agent can choose via send_message."""
    result = await slack_client.reply_thread_id(
        _msg(kind=RoomKind.public, channel="C1")
    )
    assert result == ""
