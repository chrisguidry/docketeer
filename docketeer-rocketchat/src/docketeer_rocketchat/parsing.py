"""Parsing helpers for Rocket Chat message data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from docketeer.chat import Attachment


def parse_rc_timestamp(ts: Any) -> datetime | None:
    """Parse a Rocket Chat timestamp into a datetime."""
    if isinstance(ts, dict) and "$date" in ts:
        return datetime.fromtimestamp(ts["$date"] / 1000, tz=UTC)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
    return None


def parse_attachments(raw: list[dict[str, Any]]) -> list[Attachment]:
    """Extract image attachments from a Rocket Chat attachment list."""
    return [
        Attachment(
            url=image_url,
            media_type=att.get("image_type", "image/png"),
            title=att.get("title", ""),
        )
        for att in raw
        if (image_url := att.get("image_url"))
    ]
