"""Tests for the ATProto Jetstream band."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from docketeer.antenna import SignalFilter
from docketeer_atproto import create_band
from docketeer_atproto.band import JetstreamBand, _message_to_signal


def test_create_band() -> None:
    band = create_band()
    assert isinstance(band, JetstreamBand)
    assert band.name == "atproto"


def _sample_message(
    *,
    time_us: int = 1_700_000_000_000_000,
    did: str = "did:plc:abc123",
    collection: str = "app.bsky.feed.post",
    operation: str = "create",
) -> dict[str, Any]:
    return {
        "time_us": time_us,
        "did": did,
        "commit": {
            "collection": collection,
            "operation": operation,
        },
    }


class TestRemoteFilterHints:
    def test_collection_eq(self) -> None:
        band = JetstreamBand()
        filters = [SignalFilter(path="collection", op="eq", value="app.bsky.feed.post")]
        hints = band.remote_filter_hints(filters)
        assert hints == filters

    def test_collection_startswith(self) -> None:
        band = JetstreamBand()
        filters = [
            SignalFilter(path="collection", op="startswith", value="app.bsky.feed")
        ]
        hints = band.remote_filter_hints(filters)
        assert hints == filters

    def test_did_eq(self) -> None:
        band = JetstreamBand()
        filters = [SignalFilter(path="did", op="eq", value="did:plc:abc123")]
        hints = band.remote_filter_hints(filters)
        assert hints == filters

    def test_excludes_non_matching(self) -> None:
        band = JetstreamBand()
        filters = [
            SignalFilter(path="payload.action", op="eq", value="create"),
            SignalFilter(path="did", op="contains", value="plc"),
            SignalFilter(path="collection", op="ne", value="app.bsky.feed.post"),
        ]
        hints = band.remote_filter_hints(filters)
        assert hints == []

    def test_mixed_filters(self) -> None:
        band = JetstreamBand()
        collection_filter = SignalFilter(
            path="collection", op="eq", value="app.bsky.feed.post"
        )
        did_filter = SignalFilter(path="did", op="eq", value="did:plc:abc123")
        unrelated = SignalFilter(path="payload.action", op="eq", value="create")
        hints = band.remote_filter_hints([collection_filter, did_filter, unrelated])
        assert hints == [collection_filter, did_filter]


class TestMessageToSignal:
    def test_basic_message(self) -> None:
        msg = _sample_message()
        signal = _message_to_signal(msg)

        assert signal.band == "atproto"
        assert signal.signal_id == "1700000000000000"
        assert signal.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        assert signal.topic == "app.bsky.feed.post"
        assert signal.payload == msg
        assert signal.summary == "did:plc:abc123 create app.bsky.feed.post"

    def test_missing_fields(self) -> None:
        msg: dict[str, Any] = {}
        signal = _message_to_signal(msg)

        assert signal.signal_id == "0"
        assert signal.topic == ""
        assert signal.summary == " unknown "
        assert signal.timestamp == datetime(1970, 1, 1, tzinfo=UTC)


class TestContextManager:
    async def test_aenter_aexit(self) -> None:
        band = JetstreamBand()
        async with band as b:
            assert b is band


class FakeWebSocket:
    """Simulates an async iterable WebSocket connection."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = messages

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        for msg in self._messages:
            yield json.dumps(msg)


@asynccontextmanager
async def fake_connect(
    url: str,
    messages: list[dict[str, Any]] | None = None,
) -> AsyncIterator[FakeWebSocket]:
    """Drop-in replacement for websockets.connect as an async context manager."""
    yield FakeWebSocket(messages or [])


class TestListen:
    async def test_yields_signals(self) -> None:
        messages = [_sample_message(), _sample_message(operation="delete")]

        with patch(
            "docketeer_atproto.band.websockets.connect",
            return_value=fake_connect("unused", messages),
        ):
            band = JetstreamBand()
            signals = []
            async for signal in band.listen("app.bsky.feed.post", []):
                signals.append(signal)

        assert len(signals) == 2
        assert signals[0].summary == "did:plc:abc123 create app.bsky.feed.post"
        assert signals[1].summary == "did:plc:abc123 delete app.bsky.feed.post"

    async def test_cursor_from_last_signal_id(self) -> None:
        captured_urls: list[str] = []

        original_fake = fake_connect

        def capturing_connect(url: str) -> Any:
            captured_urls.append(url)
            return original_fake(url, [])

        with patch(
            "docketeer_atproto.band.websockets.connect",
            side_effect=capturing_connect,
        ):
            band = JetstreamBand()
            async for _ in band.listen(
                "app.bsky.feed.post",
                [],
                last_signal_id="1700000000000000",
            ):
                pass  # pragma: no cover

        assert len(captured_urls) == 1
        assert "cursor=1700000000000000" in captured_urls[0]

    async def test_did_filter_in_url(self) -> None:
        captured_urls: list[str] = []

        original_fake = fake_connect

        def capturing_connect(url: str) -> Any:
            captured_urls.append(url)
            return original_fake(url, [])

        band = JetstreamBand()
        filters = [
            SignalFilter(path="did", op="eq", value="did:plc:abc123"),
            SignalFilter(path="collection", op="eq", value="app.bsky.feed.post"),
        ]
        with patch(
            "docketeer_atproto.band.websockets.connect",
            side_effect=capturing_connect,
        ):
            async for _ in band.listen("app.bsky.feed.post", filters):
                pass  # pragma: no cover

        assert len(captured_urls) == 1
        assert "wantedDids=did%3Aplc%3Aabc123" in captured_urls[0]

    async def test_collection_filter_skipped_in_url(self) -> None:
        captured_urls: list[str] = []

        original_fake = fake_connect

        def capturing_connect(url: str) -> Any:
            captured_urls.append(url)
            return original_fake(url, [])

        band = JetstreamBand()
        filters = [SignalFilter(path="collection", op="eq", value="app.bsky.feed.post")]
        with patch(
            "docketeer_atproto.band.websockets.connect",
            side_effect=capturing_connect,
        ):
            async for _ in band.listen("app.bsky.feed.post", filters):
                pass  # pragma: no cover

        assert len(captured_urls) == 1
        assert captured_urls[0].count("wantedCollections") == 1

    async def test_no_cursor_without_last_signal_id(self) -> None:
        captured_urls: list[str] = []

        original_fake = fake_connect

        def capturing_connect(url: str) -> Any:
            captured_urls.append(url)
            return original_fake(url, [])

        band = JetstreamBand()
        with patch(
            "docketeer_atproto.band.websockets.connect",
            side_effect=capturing_connect,
        ):
            async for _ in band.listen("app.bsky.feed.post", []):
                pass  # pragma: no cover

        assert len(captured_urls) == 1
        assert "cursor" not in captured_urls[0]


class TestRelayUrlConfig:
    def test_default_relay_url(self) -> None:
        band = JetstreamBand()
        assert "jetstream2.us-east.bsky.network" in band._relay_url

    def test_custom_relay_url(self) -> None:
        with patch.dict(
            "os.environ",
            {"DOCKETEER_ATPROTO_RELAY_URL": "wss://custom.example.com/subscribe"},
        ):
            band = JetstreamBand()
            assert band._relay_url == "wss://custom.example.com/subscribe"
