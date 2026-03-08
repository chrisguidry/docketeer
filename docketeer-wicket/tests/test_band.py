"""Tests for the Wicket SSE band plugin."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from docketeer.antenna import Signal, SignalFilter
from docketeer_wicket import create_band
from docketeer_wicket.band import WicketBand, _unwrap_envelope


def test_create_band_returns_wicket_band():
    band = create_band()
    assert isinstance(band, WicketBand)
    assert band.name == "wicket"


# --- Envelope unwrapping ---


def _make_envelope(
    *,
    envelope_id: str = "evt-1",
    timestamp: str = "2026-03-07T12:00:00+00:00",
    path: str = "github.com/chrisguidry/docketeer",
    method: str = "POST",
    payload: Any = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "id": envelope_id,
        "timestamp": timestamp,
        "method": method,
        "path": path,
        "payload": payload if payload is not None else {"action": "created"},
    }
    return envelope


def test_unwrap_envelope_basic():
    envelope = _make_envelope()
    signal = _unwrap_envelope(envelope)

    assert signal.band == "wicket"
    assert signal.signal_id == "evt-1"
    assert signal.timestamp == datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    assert signal.topic == "github.com/chrisguidry/docketeer"
    assert signal.payload == {"action": "created"}
    assert signal.summary == ""


def test_unwrap_envelope_with_summary():
    envelope = _make_envelope(payload={"action": "created", "summary": "PR opened"})
    signal = _unwrap_envelope(envelope)
    assert signal.summary == "PR opened"


def test_unwrap_envelope_missing_fields():
    signal = _unwrap_envelope({})
    assert signal.signal_id == ""
    assert signal.topic == ""
    assert signal.payload == {}


def test_unwrap_envelope_non_dict_payload():
    envelope = _make_envelope(payload="just a string")
    signal = _unwrap_envelope(envelope)
    assert signal.payload == {"value": "just a string"}


def test_unwrap_envelope_invalid_timestamp():
    envelope = _make_envelope(timestamp="not-a-date")
    signal = _unwrap_envelope(envelope)
    assert signal.timestamp.tzinfo is not None


def test_unwrap_envelope_null_timestamp():
    envelope = _make_envelope()
    del envelope["timestamp"]
    signal = _unwrap_envelope(envelope)
    assert signal.timestamp.tzinfo is not None


# --- Remote filter hints ---


def test_remote_filter_hints_includes_payload_eq():
    band = WicketBand()
    filters = [
        SignalFilter(path="payload.action", op="eq", value="created"),
        SignalFilter(path="payload.status", op="eq", value="open"),
    ]
    result = band.remote_filter_hints(filters)
    assert result == filters


def test_remote_filter_hints_excludes_non_payload():
    band = WicketBand()
    filters = [
        SignalFilter(path="topic", op="eq", value="events"),
        SignalFilter(path="payload.action", op="eq", value="created"),
    ]
    result = band.remote_filter_hints(filters)
    assert len(result) == 1
    assert result[0].path == "payload.action"


def test_remote_filter_hints_excludes_non_eq():
    band = WicketBand()
    filters = [
        SignalFilter(path="payload.action", op="contains", value="create"),
        SignalFilter(path="payload.action", op="ne", value="deleted"),
        SignalFilter(path="payload.action", op="startswith", value="cr"),
        SignalFilter(path="payload.action", op="exists"),
    ]
    result = band.remote_filter_hints(filters)
    assert result == []


@pytest.mark.parametrize(
    ("filters", "expected_count"),
    [
        ([], 0),
        ([SignalFilter(path="payload.x", op="eq", value="1")], 1),
        (
            [
                SignalFilter(path="payload.x", op="eq", value="1"),
                SignalFilter(path="topic", op="eq", value="y"),
                SignalFilter(path="payload.z", op="ne", value="2"),
            ],
            1,
        ),
    ],
)
def test_remote_filter_hints_parametrized(
    filters: list[SignalFilter], expected_count: int
):
    band = WicketBand()
    assert len(band.remote_filter_hints(filters)) == expected_count


# --- SSE streaming tests ---


class FakeResponse:
    """Simulates an httpx streaming response with SSE lines."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


@asynccontextmanager
async def fake_stream(
    lines: list[str],
) -> AsyncIterator[tuple[AsyncMock, FakeResponse]]:
    response = FakeResponse(lines)

    @asynccontextmanager
    async def mock_stream(
        method: str, url: str, **kwargs: object
    ) -> AsyncIterator[FakeResponse]:
        yield response

    client = AsyncMock(spec=httpx.AsyncClient)
    client.stream = mock_stream
    with patch("docketeer_wicket.band.httpx.AsyncClient", return_value=client):
        yield client, response


def _sse_from_envelope(envelope: dict[str, Any], sse_id: str = "") -> list[str]:
    """Build SSE lines from a wicket envelope dict."""
    lines = []
    if sse_id:
        lines.append(f"id: {sse_id}")
    lines.append(f"data: {json.dumps(envelope)}")
    lines.append("")
    return lines


async def test_listen_parses_wicket_envelopes():
    envelope1 = _make_envelope(
        envelope_id="evt-1",
        path="hooks/github",
        payload={"action": "created"},
    )
    envelope2 = _make_envelope(
        envelope_id="evt-2",
        path="hooks/github",
        payload={"action": "updated"},
    )
    lines = _sse_from_envelope(envelope1) + _sse_from_envelope(envelope2)

    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("hooks/github", []):
                signals.append(signal)

    assert len(signals) == 2
    assert signals[0].signal_id == "evt-1"
    assert signals[0].topic == "hooks/github"
    assert signals[0].payload == {"action": "created"}
    assert signals[1].signal_id == "evt-2"
    assert signals[1].payload == {"action": "updated"}


async def test_listen_uses_sse_id_as_fallback():
    envelope = _make_envelope()
    del envelope["id"]
    lines = _sse_from_envelope(envelope, sse_id="sse-fallback")

    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("hooks", []):
                signals.append(signal)

    assert signals[0].signal_id == "sse-fallback"


async def test_listen_envelope_id_takes_precedence_over_sse_id():
    envelope = _make_envelope(envelope_id="inner-id")
    lines = ["id: sse-id", f"data: {json.dumps(envelope)}", ""]

    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("hooks", []):
                signals.append(signal)

    assert signals[0].signal_id == "inner-id"


async def test_listen_sends_last_event_id_header():
    envelope = _make_envelope()
    lines = _sse_from_envelope(envelope)
    captured_kwargs: dict[str, Any] = {}

    @asynccontextmanager
    async def capturing_stream(
        method: str, url: str, **kwargs: object
    ) -> AsyncIterator[FakeResponse]:
        captured_kwargs.update(kwargs)
        yield FakeResponse(lines)

    client = AsyncMock(spec=httpx.AsyncClient)
    client.stream = capturing_stream

    with patch("docketeer_wicket.band.httpx.AsyncClient", return_value=client):
        band = WicketBand()
        async with band:
            async for _ in band.listen("events", [], last_signal_id="evt-99"):
                pass

    headers = captured_kwargs["headers"]
    assert headers["Last-Event-ID"] == "evt-99"


async def test_listen_accept_header_always_present():
    envelope = _make_envelope()
    lines = _sse_from_envelope(envelope)
    captured_kwargs: dict[str, Any] = {}

    @asynccontextmanager
    async def capturing_stream(
        method: str, url: str, **kwargs: object
    ) -> AsyncIterator[FakeResponse]:
        captured_kwargs.update(kwargs)
        yield FakeResponse(lines)

    client = AsyncMock(spec=httpx.AsyncClient)
    client.stream = capturing_stream

    with patch("docketeer_wicket.band.httpx.AsyncClient", return_value=client):
        band = WicketBand()
        async with band:
            async for _ in band.listen("events", []):
                pass

    headers = captured_kwargs["headers"]
    assert headers["Accept"] == "text/event-stream"
    assert "Last-Event-ID" not in headers


async def test_listen_secret_adds_auth_header():
    envelope = _make_envelope()
    lines = _sse_from_envelope(envelope)
    captured_kwargs: dict[str, Any] = {}

    @asynccontextmanager
    async def capturing_stream(
        method: str, url: str, **kwargs: object
    ) -> AsyncIterator[FakeResponse]:
        captured_kwargs.update(kwargs)
        yield FakeResponse(lines)

    client = AsyncMock(spec=httpx.AsyncClient)
    client.stream = capturing_stream

    with patch("docketeer_wicket.band.httpx.AsyncClient", return_value=client):
        band = WicketBand()
        async with band:
            async for _ in band.listen("events", [], secret="my-token"):
                pass

    headers = captured_kwargs["headers"]
    assert headers["Authorization"] == "Bearer my-token"


async def test_listen_no_secret_no_auth_header():
    envelope = _make_envelope()
    lines = _sse_from_envelope(envelope)
    captured_kwargs: dict[str, Any] = {}

    @asynccontextmanager
    async def capturing_stream(
        method: str, url: str, **kwargs: object
    ) -> AsyncIterator[FakeResponse]:
        captured_kwargs.update(kwargs)
        yield FakeResponse(lines)

    client = AsyncMock(spec=httpx.AsyncClient)
    client.stream = capturing_stream

    with patch("docketeer_wicket.band.httpx.AsyncClient", return_value=client):
        band = WicketBand()
        async with band:
            async for _ in band.listen("events", []):
                pass

    headers = captured_kwargs["headers"]
    assert "Authorization" not in headers


async def test_listen_skips_invalid_json():
    envelope = _make_envelope()
    lines = [
        "data: not-valid-json",
        "",
    ] + _sse_from_envelope(envelope)

    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1


async def test_listen_builds_url_with_filter_params():
    envelope = _make_envelope(payload={"action": "created"})
    lines = _sse_from_envelope(envelope)
    captured_kwargs: dict[str, Any] = {}

    @asynccontextmanager
    async def capturing_stream(
        method: str, url: str, **kwargs: object
    ) -> AsyncIterator[FakeResponse]:
        captured_kwargs["url"] = url
        captured_kwargs.update(kwargs)
        yield FakeResponse(lines)

    client = AsyncMock(spec=httpx.AsyncClient)
    client.stream = capturing_stream

    with patch("docketeer_wicket.band.httpx.AsyncClient", return_value=client):
        band = WicketBand()
        filters = [
            SignalFilter(path="payload.action", op="eq", value="created"),
        ]
        async with band:
            async for _ in band.listen("hooks", filters):
                pass

    assert captured_kwargs["url"] == "https://wicket.test/hooks"
    assert captured_kwargs["params"] == (("filter", "payload.action:created"),)


async def test_listen_multiline_data():
    envelope = _make_envelope()
    envelope_json = json.dumps(envelope)
    # Split across multiple data: lines
    half = len(envelope_json) // 2
    lines = [
        f"data: {envelope_json[:half]}",
        f"data: {envelope_json[half:]}",
        "",
    ]
    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1
    assert signals[0].signal_id == "evt-1"


async def test_aenter_aexit_lifecycle():
    client = AsyncMock(spec=httpx.AsyncClient)
    with patch("docketeer_wicket.band.httpx.AsyncClient", return_value=client):
        band = WicketBand()
        assert band._client is None

        async with band:
            assert band._client is not None

        assert band._client is None
    client.aclose.assert_awaited_once()


async def test_aexit_without_aenter():
    band = WicketBand()
    await band.__aexit__(None, None, None)
    assert band._client is None


async def test_listen_ignores_empty_events():
    envelope = _make_envelope()
    lines = ["", ""] + _sse_from_envelope(envelope)

    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1


async def test_listen_ignores_unknown_sse_fields():
    envelope = _make_envelope()
    lines = [": this is a comment", "retry: 3000"] + _sse_from_envelope(envelope)

    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1


async def test_listen_trailing_data_without_blank_line():
    envelope = _make_envelope()
    lines = _sse_from_envelope(envelope) + ["data: incomplete"]

    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1
