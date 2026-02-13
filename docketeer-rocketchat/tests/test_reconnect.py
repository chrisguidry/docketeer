"""Tests for reconnection with backoff and _prime_history."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx

from docketeer.chat import RoomInfo, RoomKind, RoomMessage
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


async def test_incoming_messages_reconnects_on_disconnect():
    """After connection loss, reconnects and continues yielding messages."""
    client = RocketChatClient()
    client._user_id = "bot_uid"

    first_events = [_make_event("m1", "before disconnect")]
    second_events = [_make_event("m2", "after reconnect")]

    ddp1 = AsyncMock()

    async def fake_events_1() -> AsyncGenerator[dict[str, Any], None]:
        for e in first_events:
            yield e

    ddp1.events = fake_events_1

    ddp2 = AsyncMock()

    async def fake_events_2() -> AsyncGenerator[dict[str, Any], None]:
        for e in second_events:
            yield e

    ddp2.events = fake_events_2

    client._ddp = ddp1

    async def fake_open_connections() -> None:
        client._ddp = ddp2
        client._http = AsyncMock()
        client._user_id = "bot_uid"

    client._open_connections = fake_open_connections  # type: ignore[assignment]
    client.subscribe_to_my_messages = AsyncMock()  # type: ignore[assignment]
    client.set_status = AsyncMock()  # type: ignore[assignment]

    results = []
    with patch("asyncio.sleep", new_callable=AsyncMock):
        async for msg in client.incoming_messages():
            results.append(msg)
            if len(results) == 2:
                break

    assert len(results) == 2
    assert results[0].text == "before disconnect"
    assert results[1].text == "after reconnect"


async def test_incoming_messages_backoff_on_reconnect_failure():
    """Backoff doubles on each failed reconnect, capped at 60s."""
    client = RocketChatClient()
    client._user_id = "bot_uid"

    ddp = AsyncMock()

    async def fake_events() -> AsyncGenerator[dict[str, Any], None]:
        yield _make_event("m1", "hello")

    ddp.events = fake_events
    client._ddp = ddp

    connect_attempts = 0

    async def failing_open_connections() -> None:
        nonlocal connect_attempts
        connect_attempts += 1
        if connect_attempts >= 3:
            raise asyncio.CancelledError()
        raise ConnectionError("refused")

    client._open_connections = failing_open_connections  # type: ignore[assignment]
    client.subscribe_to_my_messages = AsyncMock()  # type: ignore[assignment]
    client.set_status = AsyncMock()  # type: ignore[assignment]

    sleep_values: list[float] = []

    async def tracking_sleep(seconds: float) -> None:
        sleep_values.append(seconds)

    results = []
    with patch("asyncio.sleep", side_effect=tracking_sleep):
        try:
            async for msg in client.incoming_messages():
                results.append(msg)
        except asyncio.CancelledError:
            pass

    assert len(results) == 1
    assert sleep_values == [1, 2, 4]


async def test_incoming_messages_calls_on_history():
    """The on_history callback is called with room history on connect."""
    client = RocketChatClient()
    client._user_id = "bot_uid"

    ddp = AsyncMock()

    async def fake_events() -> AsyncGenerator[dict[str, Any], None]:
        yield _make_event("m1", "hello")

    ddp.events = fake_events
    client._ddp = ddp
    client._http = httpx.AsyncClient(base_url="http://localhost:3000/api/v1", timeout=5)

    rooms = [RoomInfo(room_id="r1", kind=RoomKind.direct, members=["bot", "alice"])]
    history_msgs = [
        RoomMessage(
            message_id="h1",
            timestamp=datetime(2026, 2, 6, 15, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="hi",
        ),
    ]

    history_calls: list[tuple[RoomInfo, list[RoomMessage]]] = []

    async def record_history(room: RoomInfo, messages: list[RoomMessage]) -> None:
        history_calls.append((room, messages))

    with (
        patch.object(client, "subscribe_to_my_messages", new_callable=AsyncMock),
        patch.object(client, "set_status", new_callable=AsyncMock),
        patch.object(client, "list_rooms", return_value=rooms),
        patch.object(client, "fetch_messages", return_value=history_msgs),
    ):
        async for _msg in client.incoming_messages(on_history=record_history):
            break

    assert len(history_calls) == 1
    assert history_calls[0][0].room_id == "r1"
    assert len(history_calls[0][1]) == 1


async def test_incoming_messages_updates_high_water():
    """Messages with timestamps update the high water mark."""
    client = RocketChatClient()
    client._user_id = "bot_uid"

    ts = {"$date": int(datetime(2026, 2, 10, 12, 0, tzinfo=UTC).timestamp() * 1000)}
    ddp = AsyncMock()

    async def fake_events() -> AsyncGenerator[dict[str, Any], None]:
        yield {
            "msg": "changed",
            "fields": {
                "args": [
                    {
                        "_id": "m1",
                        "msg": "hello",
                        "rid": "r1",
                        "u": {"_id": "user1", "username": "alice"},
                        "ts": ts,
                    }
                ]
            },
        }

    ddp.events = fake_events
    client._ddp = ddp

    assert client._high_water is None
    with patch.object(client, "_after_connect", new_callable=AsyncMock):
        async for _msg in client.incoming_messages():
            break
    assert client._high_water == datetime(2026, 2, 10, 12, 0, tzinfo=UTC)


async def test_prime_history_list_rooms_failure():
    """_prime_history handles list_rooms failure gracefully."""
    client = RocketChatClient()
    calls: list[object] = []

    async def record(room: object, msgs: object) -> None:
        calls.append(room)

    with patch.object(client, "list_rooms", side_effect=ConnectionError("boom")):
        await client._prime_history(record)

    assert calls == []


async def test_prime_history_fetch_messages_failure():
    """_prime_history handles per-room fetch_messages failure gracefully."""
    client = RocketChatClient()
    rooms = [RoomInfo(room_id="r1", kind=RoomKind.direct, members=["bot", "alice"])]
    calls: list[object] = []

    async def record(room: RoomInfo, msgs: object) -> None:
        calls.append(room)

    with (
        patch.object(client, "list_rooms", return_value=rooms),
        patch.object(client, "fetch_messages", side_effect=ConnectionError("boom")),
    ):
        await client._prime_history(record)

    assert calls == []


async def test_prime_history_filters_to_dms_and_drops_self():
    """_prime_history only loads DM rooms and skips self-DMs."""
    client = RocketChatClient()
    username = client.username
    rooms = [
        RoomInfo(room_id="dm1", kind=RoomKind.direct, members=[username, "alice"]),
        RoomInfo(room_id="self", kind=RoomKind.direct, members=[username]),
        RoomInfo(
            room_id="ch1", kind=RoomKind.public, members=[username], name="general"
        ),
    ]
    msgs = [
        RoomMessage(
            message_id="h1",
            timestamp=datetime(2026, 2, 6, 15, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="hi",
        ),
    ]
    loaded_rooms: list[str] = []

    async def record(room: RoomInfo, messages: list[RoomMessage]) -> None:
        loaded_rooms.append(room.room_id)

    with (
        patch.object(client, "list_rooms", return_value=rooms),
        patch.object(client, "fetch_messages", return_value=msgs),
    ):
        await client._prime_history(record)

    assert loaded_rooms == ["dm1"]


async def test_prime_history_does_not_regress_high_water():
    """Messages older than the current high water mark don't move it backwards."""
    client = RocketChatClient()
    client._high_water = datetime(2026, 2, 10, 12, 0, tzinfo=UTC)

    username = client.username
    rooms = [RoomInfo(room_id="r1", kind=RoomKind.direct, members=[username, "alice"])]
    old_msg = [
        RoomMessage(
            message_id="h1",
            timestamp=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="old",
        ),
    ]

    async def noop(room: RoomInfo, msgs: list[RoomMessage]) -> None:
        pass

    with (
        patch.object(client, "list_rooms", return_value=rooms),
        patch.object(client, "fetch_messages", return_value=old_msg),
    ):
        await client._prime_history(noop)

    assert client._high_water == datetime(2026, 2, 10, 12, 0, tzinfo=UTC)


async def test_prime_history_empty_messages_skipped():
    """Rooms with no messages don't trigger the callback."""
    client = RocketChatClient()
    rooms = [RoomInfo(room_id="r1", kind=RoomKind.direct, members=["bot", "alice"])]
    calls: list[object] = []

    async def record(room: RoomInfo, msgs: object) -> None:
        calls.append(room)

    with (
        patch.object(client, "list_rooms", return_value=rooms),
        patch.object(client, "fetch_messages", return_value=[]),
    ):
        await client._prime_history(record)

    assert calls == []
