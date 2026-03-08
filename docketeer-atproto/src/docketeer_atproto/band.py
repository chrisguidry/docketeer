"""ATProto Jetstream WebSocket band."""

import json
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from urllib.parse import urlencode

import websockets

from docketeer.antenna import Band, Signal, SignalFilter

DEFAULT_RELAY_URL = "wss://jetstream2.us-east.bsky.network/subscribe"


class JetstreamBand(Band):
    """Streams ATProto events from a Jetstream relay via WebSocket."""

    name = "atproto"

    def __init__(self) -> None:
        self._relay_url = os.environ.get(
            "DOCKETEER_ATPROTO_RELAY_URL",
            DEFAULT_RELAY_URL,
        )

    async def __aenter__(self) -> "JetstreamBand":
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass

    async def listen(
        self,
        topic: str,
        filters: list[SignalFilter],
        last_signal_id: str = "",
    ) -> AsyncGenerator[Signal, None]:
        params: dict[str, str] = {"wantedCollections": topic}

        for hint in self.remote_filter_hints(filters):
            if hint.path == "did" and hint.op == "eq":
                params["wantedDids"] = hint.value

        if last_signal_id:
            params["cursor"] = last_signal_id

        url = f"{self._relay_url}?{urlencode(params, doseq=True)}"

        async with websockets.connect(url) as ws:
            async for raw in ws:
                message: dict = json.loads(raw)
                yield _message_to_signal(message)

    def remote_filter_hints(
        self,
        filters: list[SignalFilter],
    ) -> list[SignalFilter]:
        hints: list[SignalFilter] = []
        for f in filters:
            if (f.path == "collection" and f.op in ("eq", "startswith")) or (
                f.path == "did" and f.op == "eq"
            ):
                hints.append(f)
        return hints


def _message_to_signal(message: dict) -> Signal:
    time_us = message.get("time_us", 0)
    timestamp = datetime.fromtimestamp(time_us / 1_000_000, tz=UTC)

    commit = message.get("commit", {})
    collection = commit.get("collection", "")
    operation = commit.get("operation", "unknown")
    did = message.get("did", "")

    return Signal(
        band="atproto",
        signal_id=str(time_us),
        timestamp=timestamp,
        topic=collection,
        payload=message,
        summary=f"{did} {operation} {collection}",
    )
