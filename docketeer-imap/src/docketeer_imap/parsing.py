"""Parse raw RFC822 email bytes into a structured dataclass."""

import email
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

import html2text

MAX_BODY_LENGTH = 10_000
MAX_IMAGE_SIZE = 5 * 1024 * 1024

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
    images: list[tuple[str, bytes]] = field(default_factory=list)


def parse_email(raw: bytes) -> ParsedEmail:
    msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)

    blocked = tuple(p.lower() for p in _blocked_header_prefixes())
    headers: dict[str, str] = {}
    for key in msg:
        if not any(key.lower().startswith(prefix) for prefix in blocked):
            headers[key] = str(msg[key])

    date = _parse_date(msg)
    body = _extract_body(msg)
    images = _extract_images(msg)

    return ParsedEmail(
        message_id=str(msg.get("Message-ID", "")),
        from_=str(msg.get("From", "")),
        to=str(msg.get("To", "")),
        cc=str(msg.get("Cc", "")),
        subject=str(msg.get("Subject", "")),
        date=date,
        body=body[:MAX_BODY_LENGTH],
        headers=headers,
        images=images,
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
                return _html_to_markdown(str(part.get_content()))

        return ""

    content_type = msg.get_content_type()
    content = str(msg.get_content())
    if content_type == "text/html":
        return _html_to_markdown(content)
    return content


def _extract_images(msg: EmailMessage) -> list[tuple[str, bytes]]:
    """Extract image attachments from a multipart email."""
    images: list[tuple[str, bytes]] = []
    if not msg.is_multipart():
        return images

    for part in msg.walk():
        content_type = part.get_content_type()
        if not content_type.startswith("image/"):
            continue
        data = part.get_content()
        if not isinstance(data, bytes):
            continue  # pragma: no cover
        if len(data) > MAX_IMAGE_SIZE:
            continue
        images.append((content_type, data))

    return images


def _html_to_markdown(html: str) -> str:
    converter = html2text.HTML2Text()
    converter.body_width = 0
    converter.unicode_snob = True
    converter.ignore_images = True
    converter.protect_links = True
    return converter.handle(html).strip()
