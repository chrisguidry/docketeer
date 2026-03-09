"""IMAP IDLE band — monitors mailboxes for new messages."""

import asyncio
import logging
from collections.abc import AsyncGenerator

from aioimaplib import IMAP4_SSL, STOP_WAIT_SERVER_PUSH

from docketeer.antenna import Band, Signal, SignalFilter
from docketeer_imap.parsing import parse_email

log = logging.getLogger(__name__)

IDLE_TIMEOUT = 1440  # 24 minutes, safely under Gmail's 29-minute limit


class ImapBand(Band):
    """Monitors an IMAP mailbox via IDLE for new messages."""

    name = "imap"
    description = (
        "IMAP IDLE — push-style email notifications from any IMAP server.\n"
        "\n"
        "topic: the mailbox name to monitor\n"
        '  e.g. "INBOX", "Sent", "[Gmail]/All Mail"\n'
        "\n"
        "filters: match against parsed email fields (all client-side)\n"
        '  {path: "payload.from", op: "contains", value: "github.com"}\n'
        '  {path: "payload.headers.X-GitHub-Event", op: "eq", value: "push"}\n'
        '  {path: "payload.subject", op: "icontains", value: "deploy"}\n'
        "\n"
        "secrets: required — four vault paths for IMAP connection details\n"
        "  host: vault path to the IMAP server hostname\n"
        "  port: vault path to the IMAP server port\n"
        "  username: vault path to the login username\n"
        "  password: vault path to the login password\n"
        '  e.g. secrets={"host": "email/host", "port": "email/port",\n'
        '                "username": "email/username",\n'
        '                "password": "email/password"}\n'
        "  For Gmail, use an App Password (not your account password).\n"
        "\n"
        "Signals produced:\n"
        "  signal_id = IMAP UID (resumable via last_signal_id)\n"
        "  topic = mailbox name\n"
        "  payload = {from, to, cc, subject, date, message_id, body, headers}\n"
        '  summary = "From: sender — Subject: subject line"'
    )

    async def __aenter__(self) -> "ImapBand":
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
        config = _validate_secrets(secrets)
        client = IMAP4_SSL(config["host"], int(config["port"]))
        try:
            await client.wait_hello_from_server()
            await client.login(config["username"], config["password"])
            await client.select(topic)

            last_uid = int(last_signal_id) if last_signal_id else 0

            if last_uid:
                async for signal in _fetch_uids(client, topic, last_uid + 1):
                    last_uid = int(signal.signal_id)
                    yield signal

            while True:
                idle = await client.idle_start(timeout=IDLE_TIMEOUT)
                push = await client.wait_server_push()
                client.idle_done()
                await asyncio.wait_for(idle, 10)

                if push is STOP_WAIT_SERVER_PUSH:
                    continue

                has_exists = any(b"EXISTS" in line for line in push)
                if not has_exists:
                    continue  # pragma: no cover

                async for signal in _fetch_uids(
                    client, topic, last_uid + 1 if last_uid else 1
                ):
                    last_uid = int(signal.signal_id)
                    yield signal
        finally:
            await client.logout()

    def remote_filter_hints(
        self,
        filters: list[SignalFilter],
    ) -> list[SignalFilter]:
        return []


_REQUIRED_KEYS = ("host", "port", "username", "password")

_EXPECTED_FORMAT = (
    'Expected secrets={"host": "vault/path", "port": "vault/path", '
    '"username": "vault/path", "password": "vault/path"}'
)


def _validate_secrets(secrets: dict[str, str] | None) -> dict[str, str]:
    """Validate that all required IMAP connection keys are present."""
    if not secrets:
        raise ValueError(
            f"IMAP band requires secrets with connection details. {_EXPECTED_FORMAT}"
        )
    for key in _REQUIRED_KEYS:
        if key not in secrets:
            raise ValueError(
                f"IMAP secrets missing required key: {key}. {_EXPECTED_FORMAT}"
            )
    return secrets


async def _fetch_uids(
    client: IMAP4_SSL,
    mailbox: str,
    start_uid: int,
) -> AsyncGenerator[Signal, None]:
    response = await client.uid_search(f"UID {start_uid}:*")
    log.debug(
        "UID SEARCH %d:* response: result=%s, lines=%r",
        start_uid,
        response.result,
        response.lines,
    )
    uids = _parse_search_response(response.lines)
    log.debug("UID SEARCH %d:* → %d UIDs: %s", start_uid, len(uids), uids[:10])

    for uid in uids:
        signal = await _fetch_one(client, mailbox, uid)
        if signal:
            yield signal
        else:
            log.debug("UID %d: fetch returned no data, skipping", uid)


async def _fetch_one(
    client: IMAP4_SSL,
    mailbox: str,
    uid: int,
) -> Signal | None:
    response = await client.uid("fetch", str(uid), "(RFC822)")
    log.debug(
        "FETCH UID %d: result=%s, %d lines, first=%r",
        uid,
        response.result,
        len(response.lines),
        response.lines[0][:120] if response.lines else b"(empty)",
    )
    raw = _extract_rfc822(response.lines)
    if not raw:
        return None

    parsed = parse_email(raw)
    return Signal(
        band="imap",
        signal_id=str(uid),
        timestamp=parsed.date,
        topic=mailbox,
        payload={
            "from": parsed.from_,
            "to": parsed.to,
            "cc": parsed.cc,
            "subject": parsed.subject,
            "date": parsed.date.isoformat(),
            "message_id": parsed.message_id,
            "body": parsed.body,
            "headers": parsed.headers,
        },
        summary=f"From: {parsed.from_} — Subject: {parsed.subject}",
    )


def _parse_search_response(lines: list[bytes]) -> list[int]:
    if not lines:
        return []
    text = lines[0].decode().strip()
    if not text:
        return []
    try:
        return [int(uid) for uid in text.split()]
    except ValueError:
        return []


def _extract_rfc822(lines: list[bytes]) -> bytes | None:
    if len(lines) >= 2:
        return lines[1]
    return None
