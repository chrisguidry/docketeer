from datetime import UTC, datetime

import pytest

from docketeer.chat import RoomKind
from docketeer_slack.parsing import (
    conversation_kind,
    decode_message_id,
    encode_message_id,
    parse_attachments,
    parse_slack_ts,
    should_ignore_message,
)


def test_encode_decode_message_id_roundtrip():
    message_id = encode_message_id("C123", "1718123456.123456")
    assert message_id == "C123:1718123456.123456"
    assert decode_message_id(message_id) == ("C123", "1718123456.123456")


@pytest.mark.parametrize("value", ["", "C123", ":123", "C123:"])
def test_decode_message_id_invalid(value: str):
    with pytest.raises(ValueError):
        decode_message_id(value)


@pytest.mark.parametrize(("channel_id", "ts"), [("", "1"), ("C1", "")])
def test_encode_message_id_invalid(channel_id: str, ts: str):
    with pytest.raises(ValueError):
        encode_message_id(channel_id, ts)


def test_parse_slack_ts():
    dt = parse_slack_ts("1718123456.123456")
    assert dt == datetime.fromtimestamp(1718123456.123456, tz=UTC)


def test_parse_slack_ts_invalid():
    assert parse_slack_ts("abc") is None


@pytest.mark.parametrize(
    ("conversation", "expected"),
    [
        ({"is_im": True}, RoomKind.direct),
        ({"is_mpim": True}, RoomKind.group),
        ({"is_private": True}, RoomKind.private),
        ({}, RoomKind.public),
    ],
)
def test_conversation_kind(conversation: dict, expected: RoomKind):
    assert conversation_kind(conversation) is expected


def test_parse_attachments():
    attachments = parse_attachments(
        [
            {
                "url_private_download": "https://files.slack.test/a.png",
                "mimetype": "image/png",
                "title": "a.png",
            }
        ]
    )
    assert len(attachments) == 1
    assert attachments[0].url == "https://files.slack.test/a.png"
    assert attachments[0].media_type == "image/png"
    assert attachments[0].title == "a.png"


def test_parse_attachments_skips_missing_url():
    assert parse_attachments([{"title": "no-url"}]) == []


@pytest.mark.parametrize(
    ("message", "bot_user_id", "expected"),
    [
        ({"subtype": "message_changed"}, "", True),
        ({"subtype": "bot_message"}, "", True),
        ({"bot_id": "B1"}, "", True),
        ({"hidden": True}, "", True),
        ({"user": "U_BOT", "text": "mine"}, "U_BOT", False),
        ({"user": "U1", "text": "ok"}, "U_BOT", False),
    ],
)
def test_should_ignore_message(message: dict, bot_user_id: str, expected: bool):
    assert should_ignore_message(message, bot_user_id=bot_user_id) is expected
