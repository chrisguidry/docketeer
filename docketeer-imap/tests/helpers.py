"""Shared test fixtures for docketeer-imap tests."""

import asyncio
from collections import namedtuple
from typing import Any

import pytest

from docketeer.antenna import Signal, SignalFilter
from docketeer_imap.band import ImapBand

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


def fake_imap4_ssl(client: FakeImapClient) -> type:
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


def secrets(
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


async def collect_signals(
    band: ImapBand,
    topic: str,
    filters: list[SignalFilter] | None = None,
    last_signal_id: str = "",
    secrets_dict: dict[str, str] | None = None,
) -> list[Signal]:
    """Collect signals from listen(), expecting ConnectionResetError to end."""
    signals: list[Signal] = []
    with pytest.raises(ConnectionResetError):  # noqa: PT012
        async for signal in band.listen(
            topic,
            filters or [],
            last_signal_id=last_signal_id,
            secrets=secrets_dict,
        ):
            signals.append(signal)
    return signals
