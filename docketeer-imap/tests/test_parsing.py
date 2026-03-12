"""Tests for IMAP email parsing."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from docketeer_imap.parsing import (
    DEFAULT_BLOCKED_HEADER_PREFIXES,
    ParsedEmail,
    _blocked_header_prefixes,
    parse_email,
)


def _plain_email(
    *,
    subject: str = "Test Subject",
    from_: str = "alice@example.com",
    to: str = "bob@example.com",
    body: str = "Hello, world!",
    date: str = "Mon, 09 Mar 2026 12:00:00 +0000",
    message_id: str = "<abc123@mail.example.com>",
    cc: str = "",
    extra_headers: str = "",
) -> bytes:
    headers = (
        f"From: {from_}\r\n"
        f"To: {to}\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {date}\r\n"
        f"Message-ID: {message_id}\r\n"
        f"MIME-Version: 1.0\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
    )
    if cc:
        headers += f"Cc: {cc}\r\n"
    if extra_headers:
        headers += extra_headers
    return (headers + f"\r\n{body}").encode()


def _multipart_email(
    *,
    plain: str = "Plain text body",
    html: str = "<html><body><p>HTML body</p></body></html>",
) -> bytes:
    boundary = "boundary123"
    return (
        "From: alice@example.com\r\n"
        "To: bob@example.com\r\n"
        "Subject: Multipart\r\n"
        "Date: Mon, 09 Mar 2026 12:00:00 +0000\r\n"
        "Message-ID: <multi@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/alternative; boundary={boundary}\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{plain}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        f"{html}\r\n"
        f"--{boundary}--\r\n"
    ).encode()


def _html_only_email(*, html: str = "<p>Bold <b>text</b></p>") -> bytes:
    return (
        "From: alice@example.com\r\n"
        "To: bob@example.com\r\n"
        "Subject: HTML Only\r\n"
        "Date: Mon, 09 Mar 2026 12:00:00 +0000\r\n"
        "Message-ID: <html@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        f"{html}"
    ).encode()


def test_parse_plain_text() -> None:
    parsed = parse_email(_plain_email())

    assert isinstance(parsed, ParsedEmail)
    assert parsed.from_ == "alice@example.com"
    assert parsed.to == "bob@example.com"
    assert parsed.subject == "Test Subject"
    assert parsed.body == "Hello, world!"
    assert parsed.message_id == "<abc123@mail.example.com>"
    assert parsed.cc == ""


def test_parse_multipart_prefers_text() -> None:
    parsed = parse_email(_multipart_email())

    assert parsed.body == "Plain text body"
    assert "HTML" not in parsed.body


def test_parse_html_only_strips_tags() -> None:
    parsed = parse_email(_html_only_email(html="<p>Hello <b>world</b></p>"))

    assert parsed.body == "Hello world"


def test_parse_encoded_subject() -> None:
    raw = _plain_email(subject="=?utf-8?B?SGVsbG8gV29ybGQ=?=")
    parsed = parse_email(raw)

    assert parsed.subject == "Hello World"


def test_parse_date_formats() -> None:
    raw = _plain_email(date="09 Mar 2026 15:30:00 -0500")
    parsed = parse_email(raw)

    assert parsed.date.year == 2026
    assert parsed.date.month == 3
    assert parsed.date.day == 9


def test_parse_date_missing() -> None:
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: No Date\r\n"
        b"Message-ID: <nodate@example.com>\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"body"
    )

    now = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)
    with patch("docketeer_imap.parsing.datetime") as mock_dt:
        mock_dt.now.return_value = now
        parsed = parse_email(raw)

    assert parsed.date == now


def test_parse_body_truncation() -> None:
    long_body = "x" * 15_000
    raw = _plain_email(body=long_body)
    parsed = parse_email(raw)

    assert len(parsed.body) == 10_000


def test_parse_missing_headers() -> None:
    raw = b"Content-Type: text/plain\r\n\r\njust a body"

    now = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)
    with patch("docketeer_imap.parsing.datetime") as mock_dt:
        mock_dt.now.return_value = now
        parsed = parse_email(raw)

    assert parsed.from_ == ""
    assert parsed.to == ""
    assert parsed.subject == ""
    assert parsed.message_id == ""
    assert parsed.cc == ""
    assert parsed.body == "just a body"


def test_parse_charset() -> None:
    raw = (
        b"From: alice@example.com\r\n"
        b"To: bob@example.com\r\n"
        b"Subject: Latin1\r\n"
        b"Date: Mon, 09 Mar 2026 12:00:00 +0000\r\n"
        b"Message-ID: <latin@example.com>\r\n"
        b"Content-Type: text/plain; charset=iso-8859-1\r\n"
        b"\r\n"
    ) + "r\xe9sum\xe9".encode("iso-8859-1")

    parsed = parse_email(raw)
    assert "sum" in parsed.body


def test_parse_cc_header() -> None:
    raw = _plain_email(cc="dave@example.com")
    parsed = parse_email(raw)

    assert parsed.cc == "dave@example.com"


def test_parse_extra_headers_included() -> None:
    raw = _plain_email(
        extra_headers=(
            "X-GitHub-Event: pull_request\r\nList-Id: docketeer.github.com\r\n"
        ),
    )
    parsed = parse_email(raw)

    assert parsed.headers["X-GitHub-Event"] == "pull_request"
    assert parsed.headers["List-Id"] == "docketeer.github.com"


def test_parse_all_headers_present() -> None:
    raw = _plain_email()
    parsed = parse_email(raw)

    assert "From" in parsed.headers
    assert "To" in parsed.headers
    assert "Subject" in parsed.headers


def test_parse_html_strips_entities() -> None:
    parsed = parse_email(_html_only_email(html="<p>A &amp; B</p>"))
    assert "A & B" in parsed.body


def test_parse_invalid_date() -> None:
    raw = _plain_email(date="not a real date at all !!!")
    now = datetime(2026, 3, 9, 12, 0, 0, tzinfo=UTC)
    with patch("docketeer_imap.parsing.datetime") as mock_dt:
        mock_dt.now.return_value = now
        parsed = parse_email(raw)

    assert parsed.date == now


def test_parse_multipart_html_fallback() -> None:
    """Multipart with no text/plain falls back to text/html."""
    boundary = "boundary456"
    raw = (
        "From: alice@example.com\r\n"
        "To: bob@example.com\r\n"
        "Subject: HTML Only Multi\r\n"
        "Date: Mon, 09 Mar 2026 12:00:00 +0000\r\n"
        "Message-ID: <htmlmulti@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/alternative; boundary={boundary}\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        "<p>HTML only in multipart</p>\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    parsed = parse_email(raw)
    assert parsed.body == "HTML only in multipart"


def test_parse_multipart_empty() -> None:
    """Multipart with no text parts returns empty body."""
    boundary = "boundary789"
    raw = (
        "From: alice@example.com\r\n"
        "To: bob@example.com\r\n"
        "Subject: Empty Multi\r\n"
        "Date: Mon, 09 Mar 2026 12:00:00 +0000\r\n"
        "Message-ID: <empty@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        f"Content-Type: multipart/mixed; boundary={boundary}\r\n"
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: application/octet-stream\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        "AQID\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    parsed = parse_email(raw)
    assert parsed.body == ""


def test_blocked_headers_excluded() -> None:
    raw = _plain_email(
        extra_headers=(
            "DKIM-Signature: v=1; a=rsa-sha256; d=example.com\r\n"
            "X-Spam-Score: 0.5\r\n"
            "ARC-Seal: i=1; a=rsa-sha256\r\n"
            "X-GitHub-Event: push\r\n"
        ),
    )
    parsed = parse_email(raw)

    assert "X-GitHub-Event" in parsed.headers
    assert "DKIM-Signature" not in parsed.headers
    assert "X-Spam-Score" not in parsed.headers
    assert "ARC-Seal" not in parsed.headers


@pytest.mark.parametrize(
    "prefix",
    DEFAULT_BLOCKED_HEADER_PREFIXES,
    ids=DEFAULT_BLOCKED_HEADER_PREFIXES,
)
def test_each_default_prefix_blocks(prefix: str) -> None:
    header_name = prefix if not prefix.endswith("-") else f"{prefix}Test"
    raw = _plain_email(extra_headers=f"{header_name}: some value\r\n")
    parsed = parse_email(raw)

    assert header_name not in parsed.headers


def test_blocked_header_prefixes_envvar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKETEER_IMAP_BLOCKED_HEADER_PREFIXES", "X-Custom-,X-Other-")
    prefixes = _blocked_header_prefixes()

    assert prefixes == ("X-Custom-", "X-Other-")


def test_blocked_header_prefixes_envvar_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKETEER_IMAP_BLOCKED_HEADER_PREFIXES", "")
    prefixes = _blocked_header_prefixes()

    assert prefixes == ()


def test_blocked_header_prefixes_default() -> None:
    assert _blocked_header_prefixes() == DEFAULT_BLOCKED_HEADER_PREFIXES


def test_envvar_disables_all_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKETEER_IMAP_BLOCKED_HEADER_PREFIXES", "")
    raw = _plain_email(
        extra_headers="DKIM-Signature: v=1; a=rsa-sha256\r\nX-Spam-Score: 0.5\r\n",
    )
    parsed = parse_email(raw)

    assert "DKIM-Signature" in parsed.headers
    assert "X-Spam-Score" in parsed.headers


def test_blocked_prefixes_match_case_insensitively() -> None:
    raw = _plain_email(
        extra_headers=(
            "dkim-signature: v=1; a=rsa-sha256\r\n"
            "x-spam-score: 0.5\r\n"
            "x-github-event: push\r\n"
        ),
    )
    parsed = parse_email(raw)

    assert "dkim-signature" not in parsed.headers
    assert "x-spam-score" not in parsed.headers
    assert "x-github-event" in parsed.headers
