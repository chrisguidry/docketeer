"""Tests for the IMAP IDLE band."""

import asyncio
from collections import namedtuple
from typing import Any
from unittest.mock import patch

import pytest
from aioimaplib import STOP_WAIT_SERVER_PUSH

from docketeer.antenna import Signal, SignalFilter
from docketeer_imap import create_band
from docketeer_imap.band import ImapBand, _extract_rfc822, _parse_search_response

Response = namedtuple("Response", "result lines")

SAMPLE_EMAIL = (
    b"From: alice@example.com\r\n"
    b"To: bob@example.com\r\n"
    b"Subject: Deploy failed\r\n"
    b"Date: Mon, 09 Mar 2026 12:00:00 +0000\r\n"
    b"Message-ID: <abc123@mail.gmail.com>\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"The deploy to prod-east failed."
)

SAMPLE_EMAIL_2 = (
    b"From: charlie@example.com\r\n"
    b"To: bob@example.com\r\n"
    b"Subject: Build passed\r\n"
    b"Date: Mon, 09 Mar 2026 13:00:00 +0000\r\n"
    b"Message-ID: <def456@mail.gmail.com>\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"All green."
)

# Sentinel that signals the fake to raise ConnectionResetError
_DISCONNECT = object()


class FakeImapClient:
    """Simulates aioimaplib.IMAP4_SSL without network I/O.

    push_sequence is a list of responses for wait_server_push. Each entry is:
    - [b"EXISTS"] — signals new mail arrived
    - STOP_WAIT_SERVER_PUSH — IDLE timed out, re-enter IDLE
    - _DISCONNECT — raises ConnectionResetError (end of test)
    """

    def __init__(
        self,
        messages: dict[int, bytes],
        *,
        push_sequence: list[Any] | None = None,
    ) -> None:
        self._messages = messages
        self._push_sequence = push_sequence or [_DISCONNECT]
        self._push_index = 0
        self.selected_mailbox: str | None = None
        self.logged_in_as: tuple[str, str] | None = None
        self.logged_out = False
        self.host: str = ""
        self.port: int = 0

    async def wait_hello_from_server(self) -> None:
        pass

    async def login(self, user: str, password: str) -> Response:
        self.logged_in_as = (user, password)
        return Response("OK", [b"LOGIN completed"])

    async def select(self, mailbox: str = "INBOX") -> Response:
        self.selected_mailbox = mailbox
        return Response("OK", [b"SELECT completed"])

    async def uid_search(self, *criteria: str) -> Response:
        criteria_str = " ".join(criteria)
        range_spec = criteria_str.removeprefix("UID ").strip()
        start_str = range_spec.split(":")[0]
        start = int(start_str)
        matching = [uid for uid in sorted(self._messages) if uid >= start]

        if matching:
            uid_list = " ".join(str(u) for u in matching)
            return Response("OK", [uid_list.encode(), b"SEARCH completed"])
        return Response("OK", [b"", b"SEARCH completed"])

    async def uid(self, command: str, *criteria: str) -> Response:
        if command == "fetch":
            uid_str = criteria[0]
            uid = int(uid_str)
            data_item = criteria[1] if len(criteria) > 1 else "(RFC822)"
            if uid in self._messages:
                raw = self._messages[uid]
                return Response(
                    "OK",
                    [
                        f"{uid} FETCH (UID {uid} {data_item} {{{len(raw)}}}".encode(),
                        raw,
                        b")",
                    ],
                )
            return Response("OK", [])

        return Response("NO", [b"Unknown command"])

    async def idle_start(self, timeout: float = 0) -> asyncio.Future[None]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        future.set_result(None)
        return future

    async def wait_server_push(self) -> list[bytes]:
        if self._push_index >= len(self._push_sequence):
            raise ConnectionResetError("fake connection closed")

        item = self._push_sequence[self._push_index]
        self._push_index += 1

        if item is _DISCONNECT:
            raise ConnectionResetError("fake connection closed")

        result: list[bytes] = item  # type: ignore[assignment]
        return result

    def idle_done(self) -> None:
        pass

    async def logout(self) -> None:
        self.logged_out = True


def _fake_imap4_ssl(client: FakeImapClient) -> type:
    class PatchedIMAP4_SSL:
        def __init__(self, host: str = "", port: int = 993) -> None:
            client.host = host
            client.port = port

        async def wait_hello_from_server(self) -> None:
            return await client.wait_hello_from_server()

        async def login(self, user: str, password: str) -> Response:
            return await client.login(user, password)

        async def select(self, mailbox: str = "INBOX") -> Response:
            return await client.select(mailbox)

        async def uid_search(self, *criteria: str) -> Response:
            return await client.uid_search(*criteria)

        async def uid(self, command: str, *criteria: str) -> Response:
            return await client.uid(command, *criteria)

        async def idle_start(self, timeout: float = 0) -> asyncio.Future[None]:
            return await client.idle_start(timeout)

        async def wait_server_push(self) -> list[bytes]:
            return await client.wait_server_push()

        def idle_done(self) -> None:
            client.idle_done()

        async def logout(self) -> None:
            await client.logout()

    return PatchedIMAP4_SSL


def _secrets(
    *,
    host: str = "imap.gmail.com",
    port: str = "993",
    username: str = "me@gmail.com",
    password: str = "app-password-xxxx",
) -> dict[str, str]:
    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
    }


async def _collect_signals(
    band: ImapBand,
    topic: str,
    filters: list[SignalFilter] | None = None,
    last_signal_id: str = "",
    secrets: dict[str, str] | None = None,
) -> list[Signal]:
    """Collect signals from listen(), expecting ConnectionResetError to end."""
    signals: list[Signal] = []
    with pytest.raises(ConnectionResetError):  # noqa: PT012
        async for signal in band.listen(
            topic,
            filters or [],
            last_signal_id=last_signal_id,
            secrets=secrets,
        ):
            signals.append(signal)
    return signals


def test_create_band() -> None:
    band = create_band()
    assert isinstance(band, ImapBand)
    assert band.name == "imap"


async def test_aenter_aexit() -> None:
    band = ImapBand()
    async with band as b:
        assert b is band


async def test_listen_parses_secret_and_connects() -> None:
    client = FakeImapClient(messages={})
    secrets = _secrets(
        host="imap.example.com",
        port="993",
        username="user@test.com",
        password="pw",
    )

    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        await _collect_signals(band, "INBOX", secrets=secrets)

    assert client.host == "imap.example.com"
    assert client.port == 993
    assert client.logged_in_as == ("user@test.com", "pw")
    assert client.selected_mailbox == "INBOX"
    assert client.logged_out


async def test_listen_raises_without_secrets() -> None:
    band = ImapBand()
    with pytest.raises(ValueError, match="requires secrets"):
        async for _ in band.listen("INBOX", []):
            pass  # pragma: no cover


async def test_listen_raises_on_empty_secrets() -> None:
    band = ImapBand()
    with pytest.raises(ValueError, match="requires secrets"):
        async for _ in band.listen("INBOX", [], secrets={}):
            pass  # pragma: no cover


async def test_listen_raises_on_missing_key() -> None:
    band = ImapBand()
    with pytest.raises(ValueError, match="missing required key.*host"):
        async for _ in band.listen("INBOX", [], secrets={"username": "x"}):
            pass  # pragma: no cover


async def test_listen_selects_topic_as_mailbox() -> None:
    client = FakeImapClient(messages={})
    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        await _collect_signals(band, "Sent", secrets=_secrets())

    assert client.selected_mailbox == "Sent"


async def test_listen_yields_signals() -> None:
    client = FakeImapClient(
        messages={1: SAMPLE_EMAIL, 2: SAMPLE_EMAIL_2},
        push_sequence=[[b"EXISTS"], [b"EXISTS"], _DISCONNECT],
    )

    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await _collect_signals(band, "INBOX", secrets=_secrets())

    assert len(signals) == 2  # UID tracking means each message is yielded once

    assert signals[0].band == "imap"
    assert signals[0].signal_id == "1"
    assert signals[0].topic == "INBOX"
    assert signals[0].payload["from"] == "alice@example.com"
    assert signals[0].payload["subject"] == "Deploy failed"
    assert signals[0].payload["body"] == "The deploy to prod-east failed."
    assert signals[0].summary == "From: alice@example.com \u2014 Subject: Deploy failed"

    assert signals[1].signal_id == "2"
    assert signals[1].payload["from"] == "charlie@example.com"


async def test_listen_catches_up_from_last_signal_id() -> None:
    client = FakeImapClient(messages={5: SAMPLE_EMAIL, 10: SAMPLE_EMAIL_2})

    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await _collect_signals(
            band,
            "INBOX",
            last_signal_id="4",
            secrets=_secrets(),
        )

    assert len(signals) == 2
    assert signals[0].signal_id == "5"
    assert signals[1].signal_id == "10"


async def test_listen_catchup_skips_unfetchable_uid() -> None:
    """Catch-up skips UIDs where fetch returns no data."""
    client = FakeImapClient(messages={5: SAMPLE_EMAIL})

    async def phantom_search(*criteria: str) -> Response:
        return Response("OK", [b"4 5", b"SEARCH completed"])

    client.uid_search = phantom_search  # type: ignore[assignment]

    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await _collect_signals(
            band,
            "INBOX",
            last_signal_id="3",
            secrets=_secrets(),
        )

    assert len(signals) == 1
    assert signals[0].signal_id == "5"


async def test_listen_no_catchup_without_last_signal_id() -> None:
    """Without last_signal_id, listen skips catch-up and goes straight to IDLE."""
    client = FakeImapClient(
        messages={1: SAMPLE_EMAIL},
        push_sequence=[[b"EXISTS"], _DISCONNECT],
    )

    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await _collect_signals(band, "INBOX", secrets=_secrets())

    # Got signals from IDLE, not from catch-up
    assert len(signals) == 1
    assert signals[0].signal_id == "1"


async def test_listen_logout_in_finally() -> None:
    client = FakeImapClient(
        messages={1: SAMPLE_EMAIL},
        push_sequence=[[b"EXISTS"]],
    )

    async def exploding_uid(command: str, *criteria: str) -> Response:
        raise RuntimeError("fetch exploded")

    client.uid = exploding_uid  # type: ignore[assignment]

    with (  # noqa: PT012
        patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)),
        pytest.raises(RuntimeError, match="fetch exploded"),
    ):
        band = ImapBand()
        async for _ in band.listen("INBOX", [], secrets=_secrets()):
            pass  # pragma: no cover

    assert client.logged_out


async def test_fake_client_fetch_missing_uid() -> None:
    client = FakeImapClient(messages={1: SAMPLE_EMAIL})
    response = await client.uid("fetch", "999")
    assert response.lines == []


async def test_fake_client_unknown_command() -> None:
    client = FakeImapClient(messages={})
    response = await client.uid("expunge")
    assert response.result == "NO"


async def test_fake_client_exhausted_push_sequence() -> None:
    client = FakeImapClient(messages={}, push_sequence=[_DISCONNECT])
    # First call consumes _DISCONNECT
    with pytest.raises(ConnectionResetError):
        await client.wait_server_push()
    # Second call hits the exhausted check
    with pytest.raises(ConnectionResetError):
        await client.wait_server_push()


def test_parse_search_response_uids() -> None:
    lines = [b"1 2 3", b"SEARCH completed (Success)"]
    assert _parse_search_response(lines) == [1, 2, 3]


def test_parse_search_response_empty_first_line() -> None:
    assert _parse_search_response([b"", b"SEARCH completed"]) == []


def test_parse_search_response_non_numeric() -> None:
    assert _parse_search_response([b"not uids"]) == []


def test_parse_search_response_empty_lines() -> None:
    assert _parse_search_response([]) == []


def test_extract_rfc822_short_response() -> None:
    assert _extract_rfc822([b"header only"]) is None


def test_extract_rfc822_empty() -> None:
    assert _extract_rfc822([]) is None


def test_remote_filter_hints_empty() -> None:
    band = ImapBand()
    filters = [
        SignalFilter(path="payload.from", op="eq", value="alice@example.com"),
        SignalFilter(path="payload.subject", op="contains", value="deploy"),
    ]
    assert band.remote_filter_hints(filters) == []


async def test_listen_signal_has_headers() -> None:
    email_with_headers = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: Test\r\n"
        b"Date: Mon, 09 Mar 2026 12:00:00 +0000\r\n"
        b"Message-ID: <test@example.com>\r\n"
        b"X-GitHub-Event: push\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"body"
    )
    client = FakeImapClient(
        messages={1: email_with_headers},
        push_sequence=[[b"EXISTS"], _DISCONNECT],
    )

    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await _collect_signals(band, "INBOX", secrets=_secrets())

    assert signals[0].payload["headers"]["X-GitHub-Event"] == "push"


async def test_listen_empty_search_result() -> None:
    client = FakeImapClient(messages={})

    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await _collect_signals(
            band,
            "INBOX",
            last_signal_id="999",
            secrets=_secrets(),
        )

    assert signals == []


async def test_listen_fetch_missing_uid_skipped() -> None:
    """When a UID from search doesn't return data, it's skipped."""
    client = FakeImapClient(
        messages={},  # no actual messages stored
        push_sequence=[[b"EXISTS"], _DISCONNECT],
    )

    async def search_returns_phantom(*criteria: str) -> Response:
        return Response("OK", [b"99", b"SEARCH completed"])

    client.uid_search = search_returns_phantom  # type: ignore[assignment]

    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await _collect_signals(band, "INBOX", secrets=_secrets())

    assert signals == []


async def test_listen_idle_timeout_reenter() -> None:
    """STOP_WAIT_SERVER_PUSH causes re-entry into IDLE, then EXISTS delivers."""
    client = FakeImapClient(
        messages={1: SAMPLE_EMAIL},
        push_sequence=[STOP_WAIT_SERVER_PUSH, [b"EXISTS"], _DISCONNECT],
    )

    with patch("docketeer_imap.band.IMAP4_SSL", _fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await _collect_signals(band, "INBOX", secrets=_secrets())

    assert len(signals) == 1
    assert signals[0].signal_id == "1"
