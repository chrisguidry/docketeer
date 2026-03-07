"""Build conversation digests from recent chat activity."""

import asyncio
import logging
from datetime import datetime

from docketeer import environment
from docketeer.brain.backend import InferenceBackend
from docketeer.chat import ChatClient, RoomInfo, RoomMessage
from docketeer.prompt import format_message_time

log = logging.getLogger(__name__)

ROOM_CHAR_LIMIT = environment.get_int("REVERIE_ROOM_CHAR_LIMIT", 4_000)


def _format_room_messages(room: RoomInfo, messages: list[RoomMessage]) -> str:
    """Format a room's messages with timestamps and participant info."""
    kind_label = room.kind.value
    name = room.name or room.room_id
    header = f"## #{name} ({kind_label})"

    participants = sorted({m.username for m in messages})
    participant_line = f"Participants: {', '.join(participants)}"

    lines: list[str] = []
    prev_ts: datetime | None = None
    for msg in messages:
        ts = format_message_time(msg.timestamp, prev_ts)
        lines.append(f"[{ts}] @{msg.username}: {msg.text}")
        prev_ts = msg.timestamp

    return f"{header}\n{participant_line}\n\n" + "\n".join(lines)


async def _summarize_room(
    backend: InferenceBackend,
    room: RoomInfo,
    formatted: str,
) -> str:
    """Summarize a room's messages via utility_complete, falling back to truncation."""
    name = room.name or room.room_id
    prompt = (
        f"Summarize this chat room activity concisely, preserving key topics, "
        f"decisions, and action items. Keep participant names.\n\n{formatted}"
    )
    try:
        summary = await backend.utility_complete(prompt, max_tokens=512)
        if summary.strip():
            kind_label = room.kind.value
            participants = sorted(
                {
                    line.split("@")[1].split(":")[0]
                    for line in formatted.split("\n")
                    if "] @" in line
                }
            )
            header = f"## #{name} ({kind_label}) [summarized]"
            participant_line = f"Participants: {', '.join(participants)}"
            return f"{header}\n{participant_line}\n\n{summary.strip()}"
    except Exception:
        log.warning("Failed to summarize room %s, falling back to truncation", name)
    return formatted[:ROOM_CHAR_LIMIT] + "\n[...truncated]"


async def _fetch_room_messages(
    chat: ChatClient,
    room: RoomInfo,
    since: datetime,
) -> tuple[RoomInfo, list[RoomMessage]]:
    """Fetch messages for a single room, returning empty list on failure."""
    try:
        messages = await chat.fetch_messages(room.room_id, after=since)
    except Exception:
        log.warning("Failed to fetch messages for room %s", room.room_id)
        messages = []
    return room, messages


async def build_conversation_digest(
    chat: ChatClient,
    backend: InferenceBackend | None,
    *,
    since: datetime,
    room_char_limit: int = ROOM_CHAR_LIMIT,
) -> str:
    """Build a digest of recent conversation activity across all rooms."""
    try:
        rooms = await chat.list_rooms()
    except Exception:
        log.warning("Failed to list rooms for digest")
        return ""

    rooms = [r for r in rooms if not r.room_id.startswith("__")]
    if not rooms:
        return "No chat activity since last reverie."

    results = await asyncio.gather(
        *(_fetch_room_messages(chat, room, since) for room in rooms)
    )

    sections: list[str] = []
    for room, messages in results:
        if not messages:
            continue
        formatted = _format_room_messages(room, messages)
        if len(formatted) > room_char_limit and backend is not None:
            section = await _summarize_room(backend, room, formatted)
        elif len(formatted) > room_char_limit:
            section = formatted[:room_char_limit] + "\n[...truncated]"
        else:
            section = formatted
        sections.append(section)

    if not sections:
        return "No chat activity since last reverie."

    return "\n\n".join(sections)
