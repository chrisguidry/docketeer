"""Tests for the ATProto Jetstream band."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from docketeer.antenna import SignalFilter
from docketeer_atproto import create_band
from docketeer_atproto.band import (
    DEFAULT_RELAY_URLS,
    JetstreamBand,
    _account_to_signal,
    _commit_to_signal,
    _identity_to_signal,
    _message_to_signal,
)


def test_create_band() -> None:
    band = create_band()
    assert isinstance(band, JetstreamBand)
    assert band.name == "atproto"


# --- Sample message builders ---


def _sample_commit(
    *,
    time_us: int = 1_700_000_000_000_000,
    did: str = "did:plc:abc123",
    collection: str = "app.bsky.feed.post",
    operation: str = "create",
) -> dict[str, Any]:
    return {
        "time_us": time_us,
        "did": did,
        "kind": "commit",
        "commit": {
            "collection": collection,
            "operation": operation,
        },
    }


def _sample_identity(
    *,
    time_us: int = 1_700_000_000_000_000,
    did: str = "did:plc:abc123",
    handle: str = "alice.bsky.social",
) -> dict[str, Any]:
    return {
        "time_us": time_us,
        "did": did,
        "kind": "identity",
        "identity": {
            "did": did,
            "handle": handle,
            "seq": 12345,
            "time": "2023-11-14T22:13:20Z",
        },
    }


def _sample_account(
    *,
    time_us: int = 1_700_000_000_000_000,
    did: str = "did:plc:abc123",
    active: bool = False,
) -> dict[str, Any]:
    return {
        "time_us": time_us,
        "did": did,
        "kind": "account",
        "account": {
            "active": active,
            "did": did,
            "seq": 12346,
            "time": "2023-11-14T22:13:20Z",
        },
    }


# --- Remote filter hints ---


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


# --- Message to signal conversion ---


class TestCommitToSignal:
    def test_basic_commit(self) -> None:
        msg = _sample_commit()
        signal = _commit_to_signal(
            msg, "did:plc:abc123", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        )

        assert signal.band == "atproto"
        assert signal.signal_id == "1700000000000000"
        assert signal.topic == "app.bsky.feed.post"
        assert signal.payload["did"] == "did:plc:abc123"
        assert signal.payload["operation"] == "create"
        assert signal.payload["collection"] == "app.bsky.feed.post"
        assert signal.summary == "did:plc:abc123 create app.bsky.feed.post"

    def test_commit_with_record_text(self) -> None:
        msg = _sample_commit()
        msg["commit"]["record"] = {"$type": "app.bsky.feed.post", "text": "hello world"}
        signal = _commit_to_signal(
            msg, "did:plc:abc123", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        )

        assert "hello world" in signal.summary
        assert signal.payload["record"]["text"] == "hello world"

    def test_commit_with_non_dict_record(self) -> None:
        msg = _sample_commit()
        msg["commit"]["record"] = "just a string"
        signal = _commit_to_signal(
            msg, "did:plc:abc123", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        )

        assert "record" not in signal.payload
        assert "just a string" not in signal.summary

    def test_missing_commit_fields(self) -> None:
        msg: dict[str, Any] = {"kind": "commit"}
        signal = _commit_to_signal(msg, "", datetime(1970, 1, 1, tzinfo=UTC))

        assert signal.signal_id == "0"
        assert signal.topic == ""
        assert signal.summary == " unknown "
        assert signal.payload["rkey"] == ""
        assert signal.payload["rev"] == ""


class TestIdentityToSignal:
    def test_handle_change(self) -> None:
        msg = _sample_identity(handle="alice.newdomain.com")
        signal = _identity_to_signal(
            msg, "did:plc:abc123", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        )

        assert signal.topic == "identity"
        assert signal.summary == "did:plc:abc123 is now @alice.newdomain.com"
        assert signal.payload == msg

    def test_missing_handle(self) -> None:
        msg = _sample_identity()
        msg["identity"] = {"did": "did:plc:abc123", "seq": 1, "time": ""}
        signal = _identity_to_signal(
            msg, "did:plc:abc123", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        )

        assert signal.summary == "did:plc:abc123 identity updated"

    def test_missing_identity_block(self) -> None:
        msg: dict[str, Any] = {"kind": "identity", "time_us": 0}
        signal = _identity_to_signal(msg, "", datetime(1970, 1, 1, tzinfo=UTC))

        assert signal.topic == "identity"
        assert signal.summary == " identity updated"


class TestAccountToSignal:
    def test_deactivated(self) -> None:
        msg = _sample_account(active=False)
        signal = _account_to_signal(
            msg, "did:plc:abc123", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        )

        assert signal.topic == "account"
        assert signal.summary == "did:plc:abc123 account deactivated"
        assert signal.payload == msg

    def test_active(self) -> None:
        msg = _sample_account(active=True)
        signal = _account_to_signal(
            msg, "did:plc:abc123", datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        )

        assert signal.summary == "did:plc:abc123 account active"

    def test_missing_account_block(self) -> None:
        msg: dict[str, Any] = {"kind": "account", "time_us": 0}
        signal = _account_to_signal(msg, "", datetime(1970, 1, 1, tzinfo=UTC))

        assert signal.topic == "account"
        assert signal.summary == " account active"


class TestMessageToSignal:
    def test_dispatches_commit(self) -> None:
        msg = _sample_commit()
        signal = _message_to_signal(msg)
        assert signal.topic == "app.bsky.feed.post"

    def test_dispatches_identity(self) -> None:
        msg = _sample_identity()
        signal = _message_to_signal(msg)
        assert signal.topic == "identity"
        assert "alice.bsky.social" in signal.summary

    def test_dispatches_account(self) -> None:
        msg = _sample_account()
        signal = _message_to_signal(msg)
        assert signal.topic == "account"
        assert "deactivated" in signal.summary

    def test_unknown_kind_treated_as_account(self) -> None:
        msg: dict[str, Any] = {"kind": "unknown_future_type", "time_us": 0, "did": ""}
        signal = _message_to_signal(msg)
        assert signal.topic == "account"

    def test_missing_kind_defaults_to_commit(self) -> None:
        msg: dict[str, Any] = {"time_us": 0}
        signal = _message_to_signal(msg)
        assert signal.topic == ""
        assert "unknown" in signal.summary

    def test_timestamp_parsing(self) -> None:
        msg = _sample_commit(time_us=1_700_000_000_000_000)
        signal = _message_to_signal(msg)
        assert signal.timestamp == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)


# --- Context manager ---


class TestContextManager:
    async def test_aenter_aexit(self) -> None:
        band = JetstreamBand()
        async with band as b:
            assert b is band


# --- WebSocket listen ---


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
    async def test_yields_commit_signals(self) -> None:
        messages = [_sample_commit(), _sample_commit(operation="delete")]

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

    async def test_yields_mixed_event_types(self) -> None:
        messages = [
            _sample_commit(),
            _sample_identity(),
            _sample_account(),
        ]

        with patch(
            "docketeer_atproto.band.websockets.connect",
            return_value=fake_connect("unused", messages),
        ):
            band = JetstreamBand()
            signals = []
            async for signal in band.listen("app.bsky.feed.post", []):
                signals.append(signal)

        assert len(signals) == 3
        assert signals[0].topic == "app.bsky.feed.post"
        assert signals[1].topic == "identity"
        assert signals[2].topic == "account"

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


# --- Relay URL config ---


class TestRelayUrlConfig:
    def test_default_relay_urls(self) -> None:
        band = JetstreamBand()
        assert band._relay_urls == ["wss://jetstream.waow.tech/subscribe"]

    def test_custom_relay_url(self) -> None:
        with patch.dict(
            "os.environ",
            {"DOCKETEER_ATPROTO_RELAY_URL": "wss://custom.example.com/subscribe"},
        ):
            band = JetstreamBand()
            assert band._relay_urls == ["wss://custom.example.com/subscribe"]

    def test_round_robin_across_calls(self) -> None:
        band = JetstreamBand()
        first = band._pick_relay()
        second = band._pick_relay()

        assert first == DEFAULT_RELAY_URLS[0]
        assert second == DEFAULT_RELAY_URLS[0]

    def test_round_robin_single_relay(self) -> None:
        with patch.dict(
            "os.environ",
            {"DOCKETEER_ATPROTO_RELAY_URL": "wss://only.one/subscribe"},
        ):
            band = JetstreamBand()
            assert band._pick_relay() == "wss://only.one/subscribe"
            assert band._pick_relay() == "wss://only.one/subscribe"

    async def test_listen_uses_picked_relay(self) -> None:
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

            async for _ in band.listen("app.bsky.feed.post", []):
                pass  # pragma: no cover

        assert len(captured_urls) == 2
        assert "jetstream.waow.tech" in captured_urls[0]
        assert "jetstream.waow.tech" in captured_urls[1]
