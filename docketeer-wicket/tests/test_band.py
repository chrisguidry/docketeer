"""Tests for the Wicket SSE band plugin."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from docketeer.antenna import Signal, SignalFilter
from docketeer_wicket import create_band
from docketeer_wicket.band import WicketBand


def test_create_band_returns_wicket_band():
    band = create_band()
    assert isinstance(band, WicketBand)
    assert band.name == "wicket"


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


async def test_listen_parses_sse_events():
    lines = [
        "id: evt-1",
        "event: push",
        'data: {"action": "created", "summary": "new item"}',
        "",
        "id: evt-2",
        'data: {"action": "updated"}',
        "",
    ]
    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 2

    assert signals[0].band == "wicket"
    assert signals[0].signal_id == "evt-1"
    assert signals[0].topic == "push"
    assert signals[0].payload == {"action": "created", "summary": "new item"}
    assert signals[0].summary == "new item"

    assert signals[1].signal_id == "evt-2"
    assert signals[1].topic == "events"
    assert signals[1].payload == {"action": "updated"}
    assert signals[1].summary == ""


async def test_listen_sends_last_event_id_header():
    lines = [
        'data: {"ok": true}',
        "",
    ]
    captured_kwargs: dict[str, object] = {}

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
    assert headers == {"Last-Event-ID": "evt-99"}


async def test_listen_no_last_event_id_header_when_empty():
    lines = [
        'data: {"ok": true}',
        "",
    ]
    captured_kwargs: dict[str, object] = {}

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
    assert headers == {}


async def test_listen_skips_invalid_json():
    lines = [
        "data: not-valid-json",
        "",
        'data: {"valid": true}',
        "",
    ]
    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1
    assert signals[0].payload == {"valid": True}


async def test_listen_builds_url_with_filter_params():
    lines = [
        'data: {"action": "created"}',
        "",
    ]
    captured_kwargs: dict[str, object] = {}

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
    assert captured_kwargs["params"] == {"action": "created"}


async def test_listen_multiline_data():
    lines = [
        "data: {",
        'data:   "multi": true',
        "data: }",
        "",
    ]
    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1
    assert signals[0].payload == {"multi": True}


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
    lines = [
        "",
        "",
        'data: {"ok": true}',
        "",
    ]
    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1
    assert signals[0].payload == {"ok": True}


async def test_listen_ignores_unknown_sse_fields():
    lines = [
        ": this is a comment",
        "retry: 3000",
        'data: {"ok": true}',
        "",
    ]
    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1
    assert signals[0].payload == {"ok": True}


async def test_listen_trailing_data_without_blank_line():
    lines = [
        "id: evt-1",
        'data: {"complete": true}',
        "",
        "data: incomplete",
    ]
    async with fake_stream(lines):
        band = WicketBand()
        async with band:
            signals: list[Signal] = []
            async for signal in band.listen("events", []):
                signals.append(signal)

    assert len(signals) == 1
    assert signals[0].payload == {"complete": True}


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
