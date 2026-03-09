"""ATProto Jetstream WebSocket band."""

import json
import logging
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import websockets

from docketeer.antenna import Band, Signal, SignalFilter

log = logging.getLogger(__name__)

DEFAULT_RELAY_URLS = [
    "wss://jetstream1.us-east.bsky.network/subscribe",
    "wss://jetstream2.us-east.bsky.network/subscribe",
]


class JetstreamBand(Band):
    """Streams ATProto events from a Jetstream relay via WebSocket."""

    name = "atproto"
    description = (
        "ATProto Jetstream — real-time Bluesky/AT Protocol events via WebSocket.\n"
        "\n"
        "topic: the collection NSID to subscribe to\n"
        '  e.g. "app.bsky.feed.post" for posts,\n'
        '       "app.bsky.feed.like" for likes,\n'
        '       "app.bsky.graph.follow" for follows\n'
        "\n"
        "filters: narrow the stream by DID or collection\n"
        '  {path: "did", op: "eq", value: "did:plc:..."} — single account\n'
        '  {path: "collection", op: "startswith", value: "app.bsky.feed"}\n'
        "  did and collection eq/startswith filters are pushed server-side\n"
        "\n"
        "secrets: not used (Jetstream is a public firehose)\n"
        "\n"
        "Signals produced:\n"
        "  Three event kinds, distinguished by topic:\n"
        "  commit: topic = collection NSID\n"
        "    payload.did, payload.operation, payload.collection, payload.rkey\n"
        "    payload.record = the AT Protocol record (post text, like, follow, etc.)\n"
        "    For posts: payload.record.text contains the post text\n"
        '    summary = "{did} {operation} {collection}: {post text}"\n'
        '  identity: topic = "identity" (handle/DID changes)\n'
        '    summary = "{did} is now @{handle}"\n'
        '  account: topic = "account" (activation/deactivation)\n'
        '    summary = "{did} account active/deactivated"\n'
        "\n"
        "Filtering tips:\n"
        "  To filter posts by content, use:\n"
        '    {path: "payload.record.text", op: "icontains", value: "cat"}'
    )

    def __init__(self) -> None:
        env_url = os.environ.get("DOCKETEER_ATPROTO_RELAY_URL")
        if env_url:
            self._relay_urls = [env_url]
        else:
            self._relay_urls = list(DEFAULT_RELAY_URLS)
        self._next_relay = 0

    def _pick_relay(self) -> str:
        url = self._relay_urls[self._next_relay % len(self._relay_urls)]
        self._next_relay += 1
        return url

    async def __aenter__(self) -> "JetstreamBand":
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass

    async def listen(
        self,
        topic: str,
        filters: list[SignalFilter],
        last_signal_id: str = "",
        secrets: dict[str, str] | None = None,
    ) -> AsyncGenerator[Signal, None]:
        params: dict[str, str] = {"wantedCollections": topic}

        for hint in self.remote_filter_hints(filters):
            if hint.path == "did" and hint.op == "eq":
                params["wantedDids"] = hint.value

        if last_signal_id:
            params["cursor"] = last_signal_id

        relay = self._pick_relay()
        url = f"{relay}?{urlencode(params, doseq=True)}"
        log.info("Connecting to Jetstream relay: %s", relay)

        async with websockets.connect(url) as ws:
            async for raw in ws:
                message: dict[str, Any] = json.loads(raw)
                signal = _message_to_signal(message)
                yield signal

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


def _message_to_signal(message: dict[str, Any]) -> Signal:
    time_us = message.get("time_us", 0)
    timestamp = datetime.fromtimestamp(time_us / 1_000_000, tz=UTC)
    did = message.get("did", "")
    kind = message.get("kind", "commit")

    if kind == "commit":
        return _commit_to_signal(message, did, timestamp)
    if kind == "identity":
        return _identity_to_signal(message, did, timestamp)
    return _account_to_signal(message, did, timestamp)


def _commit_to_signal(
    message: dict[str, Any],
    did: str,
    timestamp: datetime,
) -> Signal:
    commit = message.get("commit", {})
    collection = commit.get("collection", "")
    operation = commit.get("operation", "unknown")
    record = commit.get("record", {})

    summary = f"{did} {operation} {collection}"
    text = record.get("text", "") if isinstance(record, dict) else ""
    if text:
        summary = f"{summary}: {text}"

    payload: dict[str, Any] = {
        "did": did,
        "operation": operation,
        "collection": collection,
        "rkey": commit.get("rkey", ""),
        "rev": commit.get("rev", ""),
    }
    if isinstance(record, dict):
        payload["record"] = record

    return Signal(
        band="atproto",
        signal_id=str(message.get("time_us", 0)),
        timestamp=timestamp,
        topic=collection,
        payload=payload,
        summary=summary,
    )


def _identity_to_signal(
    message: dict[str, Any],
    did: str,
    timestamp: datetime,
) -> Signal:
    identity = message.get("identity", {})
    handle = identity.get("handle", "")

    return Signal(
        band="atproto",
        signal_id=str(message.get("time_us", 0)),
        timestamp=timestamp,
        topic="identity",
        payload=message,
        summary=f"{did} is now @{handle}" if handle else f"{did} identity updated",
    )


def _account_to_signal(
    message: dict[str, Any],
    did: str,
    timestamp: datetime,
) -> Signal:
    account = message.get("account", {})
    active = account.get("active", True)
    status = "active" if active else "deactivated"

    return Signal(
        band="atproto",
        signal_id=str(message.get("time_us", 0)),
        timestamp=timestamp,
        topic="account",
        payload=message,
        summary=f"{did} account {status}",
    )
