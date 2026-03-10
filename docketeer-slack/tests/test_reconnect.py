import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import websockets

from docketeer.chat import RoomInfo, RoomKind, RoomMessage
from docketeer_slack.client import SlackClient


class _FakeSocket:
    def __init__(self, messages: list[str]) -> None:
        self._messages = iter(messages)
        self.closed = False
        self.sent: list[str] = []

    def __aiter__(self) -> object:
        return self

    async def __anext__(self) -> str:
        try:
            return next(self._messages)
        except StopIteration:
            raise StopAsyncIteration

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


class _DisconnectingSocket:
    def __aiter__(self) -> object:
        return self

    async def __anext__(self) -> str:
        raise websockets.ConnectionClosed(None, None)

    async def close(self) -> None:
        pass


async def test_fake_socket_exhaustion():
    socket = _FakeSocket([])
    with pytest.raises(StopAsyncIteration):
        await socket.__anext__()


async def test_incoming_messages_yields_and_dedupes(slack_client: SlackClient):
    slack_client._ws = _FakeSocket([
        json.dumps({"envelope_id": "e1", "payload": {}}),
        json.dumps({"envelope_id": "e2", "payload": {}}),
        json.dumps({"envelope_id": "e3", "payload": {}}),
        json.dumps({"envelope_id": "e4", "payload": {}}),
    ])
    events = [
        None,
        slack_client._incoming_from_message(
            {
                "channel": "D1",
                "user": "U1",
                "text": "hello",
                "ts": "1718123456.123456",
            },
            kind=RoomKind.direct,
        ),
        slack_client._incoming_from_message(
            {
                "channel": "D1",
                "user": "U1",
                "text": "hello again",
                "ts": "1718123456.123456",
            },
            kind=RoomKind.direct,
        ),
        slack_client._incoming_from_message(
            {
                "channel": "D1",
                "user": "U2",
                "text": "world",
                "ts": "1718123457.123456",
            },
            kind=RoomKind.direct,
        ),
    ]
    with (
        patch.object(slack_client, "_open_socket", new_callable=AsyncMock),
        patch.object(slack_client, "_prime_history", new_callable=AsyncMock),
        patch.object(slack_client, "_parse_socket_event", side_effect=events),
    ):
        stream = slack_client.incoming_messages()
        first = await anext(stream)
        second = await anext(stream)
    assert [first.text, second.text] == ["hello", "world"]
    assert slack_client._high_water == datetime.fromtimestamp(1718123457.123456, tz=UTC)


async def test_incoming_messages_reconnects_after_disconnect(slack_client: SlackClient):
    first = _DisconnectingSocket()
    second = _FakeSocket([json.dumps({"envelope_id": "e1", "payload": {}})])

    async def open_socket() -> None:
        if not hasattr(open_socket, "count"):
            open_socket.count = 0
        open_socket.count += 1
        slack_client._ws = first if open_socket.count == 1 else second

    message = slack_client._incoming_from_message(
        {"channel": "D1", "user": "U1", "text": "ok", "ts": "1718123456.123456"},
        kind=RoomKind.direct,
    )

    async def parse(_event: object) -> object:
        return message

    sleep_calls = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with (
        patch.object(slack_client, "_open_socket", side_effect=open_socket),
        patch.object(slack_client, "_prime_history", new_callable=AsyncMock),
        patch.object(slack_client, "_parse_socket_event", side_effect=parse),
        patch("docketeer_slack.client.asyncio.sleep", side_effect=fake_sleep),
    ):
        msg = await anext(slack_client.incoming_messages())
        assert msg.text == "ok"
    assert sleep_calls == [1]


async def test_prime_history_calls_callback(slack_client: SlackClient):
    room = RoomInfo(room_id="D1", kind=RoomKind.direct, members=[])
    messages = [
        RoomMessage(
            message_id="D1:1718123456.123456",
            timestamp=datetime(2026, 2, 6, 12, 0, tzinfo=UTC),
            username="U1",
            display_name="U1",
            text="hi",
        )
    ]
    calls = []

    async def on_history(room_info: RoomInfo, room_messages: list[RoomMessage]) -> None:
        calls.append((room_info, room_messages))

    with (
        patch.object(slack_client, "list_rooms", return_value=[room]),
        patch.object(slack_client, "fetch_messages", return_value=messages),
    ):
        await slack_client._prime_history(on_history)
    assert len(calls) == 1
    assert slack_client._high_water == datetime(2026, 2, 6, 12, 0, tzinfo=UTC)


async def test_prime_history_does_not_regress_high_water(slack_client: SlackClient):
    slack_client._high_water = datetime(2026, 2, 7, 12, 0, tzinfo=UTC)
    room = RoomInfo(room_id="D1", kind=RoomKind.direct, members=[])
    messages = [
        RoomMessage(
            message_id="D1:1718123456.123456",
            timestamp=datetime(2026, 2, 6, 12, 0, tzinfo=UTC),
            username="U1",
            display_name="U1",
            text="hi",
        )
    ]
    with (
        patch.object(slack_client, "list_rooms", return_value=[room]),
        patch.object(slack_client, "fetch_messages", return_value=messages),
    ):
        await slack_client._prime_history(AsyncMock())
    assert slack_client._high_water == datetime(2026, 2, 7, 12, 0, tzinfo=UTC)


async def test_prime_history_list_rooms_failure(slack_client: SlackClient):
    with patch.object(slack_client, "list_rooms", side_effect=httpx.HTTPError("boom")):
        await slack_client._prime_history(AsyncMock())


async def test_prime_history_fetch_messages_failure(slack_client: SlackClient):
    room = RoomInfo(room_id="D1", kind=RoomKind.direct, members=[])
    with (
        patch.object(slack_client, "list_rooms", return_value=[room]),
        patch.object(slack_client, "fetch_messages", side_effect=httpx.HTTPError("boom")),
    ):
        await slack_client._prime_history(AsyncMock())


async def test_prime_history_skips_non_dm(slack_client: SlackClient):
    room = RoomInfo(room_id="C1", kind=RoomKind.public, members=[])
    with (
        patch.object(slack_client, "list_rooms", return_value=[room]),
        patch.object(slack_client, "fetch_messages", new_callable=AsyncMock) as fetch,
    ):
        await slack_client._prime_history(AsyncMock())
    fetch.assert_not_called()
