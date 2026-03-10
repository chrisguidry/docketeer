"""Parsing helpers for Slack message/event data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from docketeer.chat import Attachment, RoomKind


def encode_message_id(channel_id: str, ts: str) -> str:
    """Encode a Slack message target into a composite message_id."""
    if not channel_id or not ts:
        raise ValueError("message_id requires non-empty channel_id and ts")
    return f"{channel_id}:{ts}"


def decode_message_id(message_id: str) -> tuple[str, str]:
    """Decode a composite Slack message_id into channel_id and ts."""
    channel_id, sep, ts = message_id.partition(":")
    if not sep or not channel_id or not ts:
        raise ValueError(f"Invalid Slack message_id: {message_id!r}")
    return channel_id, ts


def parse_slack_ts(ts: str) -> datetime | None:
    """Parse a Slack timestamp string into UTC datetime."""
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (TypeError, ValueError):
        return None


def conversation_kind(conversation: dict[str, Any]) -> RoomKind:
    """Map a Slack conversation object to RoomKind."""
    if conversation.get("is_im"):
        return RoomKind.direct
    if conversation.get("is_mpim"):
        return RoomKind.group
    if conversation.get("is_private"):
        return RoomKind.private
    return RoomKind.public


def parse_attachments(files: list[dict[str, Any]] | None) -> list[Attachment]:
    """Extract image/file attachments from Slack file objects."""
    if not files:
        return []
    attachments: list[Attachment] = []
    for file in files:
        url = file.get("url_private_download") or file.get("url_private")
        media_type = file.get("mimetype") or "application/octet-stream"
        title = file.get("title") or file.get("name") or ""
        if url:
            attachments.append(Attachment(url=url, media_type=media_type, title=title))
    return attachments


def should_ignore_message(message: dict[str, Any], *, bot_user_id: str = "") -> bool:
    """Filter Slack message payloads we don't want to deliver to the brain."""
    subtype = message.get("subtype", "")
    if subtype in {
        "message_changed",
        "message_deleted",
        "channel_join",
        "channel_leave",
        "thread_broadcast",
        "bot_message",
    }:
        return True
    if message.get("hidden"):
        return True
    if bot_user_id and message.get("user") == bot_user_id:
        return False
    return bool(message.get("bot_id"))
