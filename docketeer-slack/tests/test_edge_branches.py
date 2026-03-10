import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.chat import RoomInfo, RoomKind
from docketeer_slack.client import SlackClient


async def test_incoming_messages_skips_ack_without_envelope(slack_client: SlackClient):
    class OneShotSocket:
        def __aiter__(self) -> object:
            return self._iter()

        async def _iter(self) -> object:
            yield "{}"

        async def close(self) -> None:
            pass

    slack_client._ws = OneShotSocket()
    with (
        patch.object(slack_client, "_open_socket", new_callable=AsyncMock),
        patch.object(slack_client, "_prime_history", new_callable=AsyncMock),
        patch.object(slack_client, "_parse_socket_event", AsyncMock(return_value=None)),
        patch.object(slack_client, "_ack", new_callable=AsyncMock) as ack,
        patch(
            "docketeer_slack.client.asyncio.sleep", side_effect=asyncio.CancelledError
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await anext(slack_client.incoming_messages())
    ack.assert_not_called()


async def test_should_handle_channel_message_negative(slack_client: SlackClient):
    slack_client._allowlist = set()
    slack_client._user_id = "U_BOT"
    assert (
        slack_client._should_handle_channel_message({"channel": "C1", "text": "hello"})
        is False
    )


async def test_incoming_from_message_without_timestamp_yields_message(
    slack_client: SlackClient,
):
    msg = slack_client._incoming_from_message(
        {"channel": "D1", "user": "U1", "text": "hello", "ts": "not-a-ts"},
        kind=RoomKind.direct,
    )
    assert msg is not None
    assert msg.timestamp is None


async def test_incoming_messages_yields_without_timestamp_update(
    slack_client: SlackClient,
):
    class OneShotSocket:
        def __aiter__(self) -> object:
            return self

        async def __anext__(self) -> str:
            if hasattr(self, "done"):
                raise StopAsyncIteration
            self.done = True
            return '{"payload": {}}'

        async def send(self, _payload: str) -> None:
            return None

        async def close(self) -> None:
            return None

    socket = OneShotSocket()
    msg = slack_client._incoming_from_message(
        {"channel": "D1", "user": "U1", "text": "hello", "ts": "bad-ts"},
        kind=RoomKind.direct,
    )
    slack_client._high_water = datetime(2026, 2, 7, 12, 0, tzinfo=UTC)

    async def open_socket() -> None:
        slack_client._ws = socket

    with (
        patch.object(slack_client, "_open_socket", side_effect=open_socket),
        patch.object(slack_client, "_prime_history", new_callable=AsyncMock),
        patch.object(slack_client, "_parse_socket_event", AsyncMock(return_value=msg)),
    ):
        yielded = await anext(slack_client.incoming_messages())
    assert yielded.timestamp is None
    assert slack_client._high_water == datetime(2026, 2, 7, 12, 0, tzinfo=UTC)
    await socket.send("noop")
    with pytest.raises(StopAsyncIteration):
        await socket.__anext__()


@patch.object(SlackClient, "_api_get", new_callable=AsyncMock)
async def test_fetch_messages_before_after_params(
    api_get: AsyncMock, slack_client: SlackClient
):
    api_get.return_value = {"messages": []}
    before = datetime(2026, 2, 6, 12, 0, tzinfo=UTC)
    after = datetime(2026, 2, 6, 11, 0, tzinfo=UTC)
    await slack_client.fetch_messages("C1", before=before, after=after)
    params = api_get.await_args.kwargs["params"]
    assert params["latest"] == before.timestamp()
    assert params["oldest"] == after.timestamp()


@patch.object(SlackClient, "_api_get", new_callable=AsyncMock)
async def test_fetch_messages_thread_parent_has_empty_thread_id(
    api_get: AsyncMock, slack_client: SlackClient
):
    api_get.return_value = {
        "messages": [
            {
                "ts": "1718123456.123456",
                "user": "U1",
                "text": "parent",
                "thread_ts": "1718123456.123456",
            }
        ]
    }
    messages = await slack_client.fetch_messages("C1")
    assert messages[0].thread_id == ""


async def test_list_rooms_cursor_branch(slack_client: SlackClient):
    results = [
        {"channels": [], "response_metadata": {"next_cursor": "NEXT"}},
        {"channels": [], "response_metadata": {"next_cursor": ""}},
    ]

    async def fake_api_get(
        _method: str, *, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        if fake_api_get.calls:
            assert params is not None
            assert params["cursor"] == "NEXT"
        fake_api_get.calls += 1
        return results[fake_api_get.calls - 1]

    fake_api_get.calls = 0
    with patch.object(slack_client, "_api_get", side_effect=fake_api_get):
        rooms = await slack_client.list_rooms()
    assert rooms == []


async def test_room_context_fetches_direct(slack_client: SlackClient):
    with patch.object(
        slack_client,
        "_api_get",
        AsyncMock(return_value={"channel": {"id": "D1", "is_im": True}}),
    ):
        assert await slack_client.room_context("D1", "alice") == "Room: DM with @alice"


async def test_prime_history_without_callback(slack_client: SlackClient):
    await slack_client._prime_history(None)


async def test_prime_history_skips_empty_messages(slack_client: SlackClient):
    room = RoomInfo(room_id="D1", kind=RoomKind.direct, members=[])
    callback = AsyncMock()
    with (
        patch.object(slack_client, "list_rooms", return_value=[room]),
        patch.object(slack_client, "fetch_messages", return_value=[]),
    ):
        await slack_client._prime_history(callback)
    callback.assert_not_called()


async def test_incoming_messages_without_socket_in_finally(slack_client: SlackClient):
    class FalseySocket:
        def __bool__(self) -> bool:
            return False

        def __aiter__(self) -> object:
            return self

        async def __anext__(self) -> str:
            raise StopAsyncIteration

    async def open_socket() -> None:
        slack_client._ws = FalseySocket()

    with (
        patch.object(slack_client, "_open_socket", side_effect=open_socket),
        patch.object(slack_client, "_prime_history", new_callable=AsyncMock),
        patch(
            "docketeer_slack.client.asyncio.sleep", side_effect=asyncio.CancelledError
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await anext(slack_client.incoming_messages())
