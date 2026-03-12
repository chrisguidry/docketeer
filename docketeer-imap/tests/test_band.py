"""Tests for the IMAP IDLE band."""

from unittest.mock import patch

import pytest
from aioimaplib import STOP_WAIT_SERVER_PUSH

from docketeer.antenna import SignalFilter
from docketeer_imap import create_band
from docketeer_imap.band import ImapBand, _extract_rfc822, _parse_search_response

from .helpers import (
    _DISCONNECT,
    SAMPLE_EMAIL,
    SAMPLE_EMAIL_2,
    FakeImapClient,
    Response,
    collect_signals,
    fake_imap4_ssl,
    secrets,
)


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
    s = secrets(
        host="imap.example.com",
        port="993",
        username="user@test.com",
        password="pw",
    )

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        await collect_signals(band, "INBOX", secrets_dict=s)

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
    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        await collect_signals(band, "Sent", secrets_dict=secrets())

    assert client.selected_mailbox == "Sent"


async def test_listen_yields_signals() -> None:
    client = FakeImapClient(
        messages={1: SAMPLE_EMAIL, 2: SAMPLE_EMAIL_2},
        push_sequence=[[b"EXISTS"], [b"EXISTS"], _DISCONNECT],
    )

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await collect_signals(band, "INBOX", secrets_dict=secrets())

    assert len(signals) == 2  # UID tracking means each message is yielded once

    assert signals[0].band == "imap"
    assert signals[0].signal_id == "1"
    assert signals[0].topic == "INBOX"
    assert signals[0].payload["from"] == "alice@example.com"
    assert signals[0].payload["subject"] == "Deploy failed"
    assert signals[0].payload["body"] == "The deploy to prod-east failed."
    assert signals[0].summary == "From: alice@example.com — Subject: Deploy failed"

    assert signals[1].signal_id == "2"
    assert signals[1].payload["from"] == "charlie@example.com"


async def test_listen_catches_up_from_last_signal_id() -> None:
    client = FakeImapClient(messages={5: SAMPLE_EMAIL, 10: SAMPLE_EMAIL_2})

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await collect_signals(
            band,
            "INBOX",
            last_signal_id="4",
            secrets_dict=secrets(),
        )

    assert len(signals) == 2
    assert signals[0].signal_id == "5"
    assert signals[1].signal_id == "10"


async def test_listen_catchup_skips_unfetchable_uid() -> None:
    """Catch-up skips UIDs where fetch returns no data."""
    client = FakeImapClient(messages={5: SAMPLE_EMAIL})

    async def phantom_search(*criteria: str) -> Response:
        return Response("OK", [b"4 5", b"SEARCH completed"])

    client.uid_search = phantom_search  # type: ignore[assignment]  # intentional override

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await collect_signals(
            band,
            "INBOX",
            last_signal_id="3",
            secrets_dict=secrets(),
        )

    assert len(signals) == 1
    assert signals[0].signal_id == "5"


async def test_listen_no_catchup_without_last_signal_id() -> None:
    """Without last_signal_id, listen skips catch-up and goes straight to IDLE."""
    client = FakeImapClient(
        messages={1: SAMPLE_EMAIL},
        push_sequence=[[b"EXISTS"], _DISCONNECT],
    )

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await collect_signals(band, "INBOX", secrets_dict=secrets())

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

    client.uid = exploding_uid  # type: ignore[assignment]  # intentional override

    with (  # noqa: PT012
        patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)),
        pytest.raises(RuntimeError, match="fetch exploded"),
    ):
        band = ImapBand()
        async for _ in band.listen("INBOX", [], secrets=secrets()):
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

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await collect_signals(band, "INBOX", secrets_dict=secrets())

    assert signals[0].payload["headers"]["X-GitHub-Event"] == "push"


async def test_listen_empty_search_result() -> None:
    client = FakeImapClient(messages={})

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await collect_signals(
            band,
            "INBOX",
            last_signal_id="999",
            secrets_dict=secrets(),
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

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await collect_signals(band, "INBOX", secrets_dict=secrets())

    assert signals == []


async def test_listen_signal_carries_images() -> None:
    """Images extracted from email MIME parts flow through to the signal."""
    import base64

    image_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    encoded = base64.b64encode(image_data).decode()
    email_with_image = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: Photo\r\n"
        b"Date: Mon, 09 Mar 2026 12:00:00 +0000\r\n"
        b"Message-ID: <img@example.com>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=imgbound\r\n"
        b"\r\n"
        b"--imgbound\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"See photo.\r\n"
        b"--imgbound\r\n"
        b"Content-Type: image/png\r\n"
        b"Content-Transfer-Encoding: base64\r\n"
        b"\r\n" + encoded.encode() + b"\r\n"
        b"--imgbound--\r\n"
    )
    client = FakeImapClient(
        messages={1: email_with_image},
        push_sequence=[[b"EXISTS"], _DISCONNECT],
    )

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await collect_signals(band, "INBOX", secrets_dict=secrets())

    assert len(signals) == 1
    assert len(signals[0].images) == 1
    assert signals[0].images[0][0] == "image/png"
    assert signals[0].images[0][1][:4] == b"\x89PNG"


async def test_listen_idle_timeout_reenter() -> None:
    """STOP_WAIT_SERVER_PUSH causes re-entry into IDLE, then EXISTS delivers."""
    client = FakeImapClient(
        messages={1: SAMPLE_EMAIL},
        push_sequence=[STOP_WAIT_SERVER_PUSH, [b"EXISTS"], _DISCONNECT],
    )

    with patch("docketeer_imap.band.IMAP4_SSL", fake_imap4_ssl(client)):
        band = ImapBand()
        signals = await collect_signals(band, "INBOX", secrets_dict=secrets())

    assert len(signals) == 1
    assert signals[0].signal_id == "1"
