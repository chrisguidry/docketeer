"""Parse raw RFC822 email bytes into a structured dataclass."""

import email
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

MAX_BODY_LENGTH = 10_000

DEFAULT_BLOCKED_HEADER_PREFIXES = (
    "ARC-",
    "Authentication-Results",
    "DKIM-",
    "DKIMCheck",
    "MIME-Version",
    "Received",
    "Return-Path",
    "SpamTally",
    "X-Brightmail-",
    "X-DKIM",
    "X-Forwarded-",
    "X-Gm-",
    "X-Google-",
    "X-Originating-IP",
    "X-Received",
    "X-Spam-",
    "X-Zone-",
)


def _blocked_header_prefixes() -> tuple[str, ...]:
    override = os.environ.get("DOCKETEER_IMAP_BLOCKED_HEADER_PREFIXES")
    if override is not None:
        return tuple(p.strip() for p in override.split(",") if p.strip())
    return DEFAULT_BLOCKED_HEADER_PREFIXES


@dataclass(frozen=True)
class ParsedEmail:
    message_id: str
    from_: str
    to: str
    cc: str
    subject: str
    date: datetime
    body: str
    headers: dict[str, str]


def parse_email(raw: bytes) -> ParsedEmail:
    msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)

    blocked = tuple(p.lower() for p in _blocked_header_prefixes())
    headers: dict[str, str] = {}
    for key in msg:
        if not any(key.lower().startswith(prefix) for prefix in blocked):
            headers[key] = str(msg[key])

    date = _parse_date(msg)
    body = _extract_body(msg)

    return ParsedEmail(
        message_id=str(msg.get("Message-ID", "")),
        from_=str(msg.get("From", "")),
        to=str(msg.get("To", "")),
        cc=str(msg.get("Cc", "")),
        subject=str(msg.get("Subject", "")),
        date=date,
        body=body[:MAX_BODY_LENGTH],
        headers=headers,
    )


def _parse_date(msg: EmailMessage) -> datetime:
    date_str = msg.get("Date")
    if date_str:
        try:
            return parsedate_to_datetime(str(date_str))
        except (ValueError, TypeError):
            pass
    return datetime.now(UTC)


def _extract_body(msg: EmailMessage) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                return str(part.get_content())

        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/html":
                return _strip_html(str(part.get_content()))

        return ""

    content_type = msg.get_content_type()
    content = str(msg.get_content())
    if content_type == "text/html":
        return _strip_html(content)
    return content


_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_MAP = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&nbsp;": " ",
}


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub("", html)
    for entity, char in _ENTITY_MAP.items():
        text = text.replace(entity, char)
    return text.strip()
