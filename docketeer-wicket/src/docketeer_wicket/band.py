"""Wicket SSE band — connects to Server-Sent Events endpoints."""

import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import httpx

from docketeer.antenna import Band, Signal, SignalFilter
from docketeer.environment import get_str

log = logging.getLogger(__name__)


def _unwrap_envelope(raw: dict[str, Any]) -> Signal:
    """Unwrap a wicket SSE envelope into a Signal."""
    signal_id = raw.get("id", "")
    timestamp_str = raw.get("timestamp")
    if timestamp_str:
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            timestamp = datetime.now(UTC)
    else:
        timestamp = datetime.now(UTC)

    topic = raw.get("path", "")
    inner = raw.get("payload", {})
    if not isinstance(inner, dict):
        inner = {"value": inner}

    return Signal(
        band="wicket",
        signal_id=signal_id,
        timestamp=timestamp,
        topic=topic,
        payload=inner,
        summary=inner.get("summary", ""),
    )


class WicketBand(Band):
    """A band that consumes Server-Sent Events streams."""

    name = "wicket"
    description = (
        "Wicket webhook relay — receives HTTP webhooks and streams them as SSE.\n"
        "\n"
        "topic: the webhook path registered with the sender\n"
        '  e.g. "github.com/chrisguidry/docketeer" for GitHub webhooks\n'
        "  The URL the sender POSTs to is {WICKET_URL}/{topic}\n"
        "\n"
        "filters: match against the webhook body (the inner payload)\n"
        "  payload.* filters with eq op are pushed server-side\n"
        '  e.g. {path: "payload.action", op: "eq", value: "opened"}\n'
        "\n"
        "secrets:\n"
        "  token: vault path to a Bearer token for authentication\n"
        '  e.g. secrets={"token": "wicket/github-token"}\n'
        "\n"
        "Signals produced:\n"
        "  signal_id = webhook envelope ID (UUID)\n"
        "  topic = webhook path (same as the topic you tuned)\n"
        "  payload = the inner webhook body (not the wicket envelope)\n"
        "  timestamp = when wicket received the webhook"
    )

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "WicketBand":
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=None))
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def listen(
        self,
        topic: str,
        filters: list[SignalFilter],
        last_signal_id: str = "",
        secrets: dict[str, str] | None = None,
    ) -> AsyncGenerator[Signal, None]:
        assert self._client is not None

        base_url = get_str("WICKET_URL")
        url = f"{base_url}/{topic}"

        params: tuple[tuple[str, str], ...] = tuple(
            ("filter", f"{f.path}:{f.value}") for f in self.remote_filter_hints(filters)
        )

        headers: dict[str, str] = {"Accept": "text/event-stream"}
        if last_signal_id:
            headers["Last-Event-ID"] = last_signal_id
        token = (secrets or {}).get("token")
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"

        log.info("Connecting to SSE stream: %s", url)
        async with self._client.stream(
            "GET", url, params=params, headers=headers
        ) as response:
            sse_id = ""
            data_lines: list[str] = []

            async for raw_line in response.aiter_lines():
                line = raw_line.rstrip("\n")

                if not line:
                    if data_lines:
                        data_str = "\n".join(data_lines)
                        try:
                            envelope = json.loads(data_str)
                        except (json.JSONDecodeError, ValueError):
                            log.warning("Skipping non-JSON SSE data: %s", data_str)
                            data_lines = []
                            sse_id = ""
                            continue

                        signal = _unwrap_envelope(envelope)
                        if not signal.signal_id and sse_id:
                            signal = Signal(
                                band=signal.band,
                                signal_id=sse_id,
                                timestamp=signal.timestamp,
                                topic=signal.topic,
                                payload=signal.payload,
                                summary=signal.summary,
                            )

                        yield signal

                    data_lines = []
                    sse_id = ""
                    continue

                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif line.startswith("id:"):
                    sse_id = line[3:].lstrip()

    def remote_filter_hints(self, filters: list[SignalFilter]) -> list[SignalFilter]:
        return [f for f in filters if f.path.startswith("payload.") and f.op == "eq"]
