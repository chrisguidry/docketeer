"""Wicket SSE band — connects to Server-Sent Events endpoints."""

import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx

from docketeer.antenna import Band, Signal, SignalFilter
from docketeer.environment import get_str

log = logging.getLogger(__name__)


class WicketBand(Band):
    """A band that consumes Server-Sent Events streams."""

    name = "wicket"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "WicketBand":
        self._client = httpx.AsyncClient()
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
    ) -> AsyncGenerator[Signal, None]:
        assert self._client is not None

        base_url = get_str("WICKET_URL")
        url = f"{base_url}/{topic}"

        params: dict[str, str] = {}
        for f in self.remote_filter_hints(filters):
            key = f.path.removeprefix("payload.")
            params[key] = f.value

        headers: dict[str, str] = {}
        if last_signal_id:
            headers["Last-Event-ID"] = last_signal_id

        async with self._client.stream(
            "GET", url, params=params, headers=headers
        ) as response:
            event_id = ""
            event_type = ""
            data_lines: list[str] = []

            async for raw_line in response.aiter_lines():
                line = raw_line.rstrip("\n")

                if not line:
                    if data_lines:
                        data_str = "\n".join(data_lines)
                        try:
                            payload = json.loads(data_str)
                        except (json.JSONDecodeError, ValueError):
                            log.warning("Skipping non-JSON SSE data: %s", data_str)
                            data_lines = []
                            event_id = ""
                            event_type = ""
                            continue

                        signal_topic = event_type or topic

                        yield Signal(
                            band="wicket",
                            signal_id=event_id,
                            timestamp=datetime.now(UTC),
                            topic=signal_topic,
                            payload=payload,
                            summary=payload.get("summary", ""),
                        )

                    data_lines = []
                    event_id = ""
                    event_type = ""
                    continue

                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif line.startswith("id:"):
                    event_id = line[3:].lstrip()
                elif line.startswith("event:"):
                    event_type = line[6:].lstrip()

    def remote_filter_hints(self, filters: list[SignalFilter]) -> list[SignalFilter]:
        return [f for f in filters if f.path.startswith("payload.") and f.op == "eq"]
