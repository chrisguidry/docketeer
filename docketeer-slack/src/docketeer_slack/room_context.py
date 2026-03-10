from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import httpx

from docketeer.chat import OnHistoryCallback, RoomInfo, RoomKind
from docketeer_slack.parsing import conversation_kind, decode_message_id

if TYPE_CHECKING:
    from docketeer_slack.client import SlackClient

log = logging.getLogger(__name__)


async def fetch_message(
    client: SlackClient, message_id: str
) -> dict[str, object] | None:
    channel, ts = decode_message_id(message_id)
    thread = await client._api_get(
        "conversations.replies", params={"channel": channel, "ts": ts}
    )
    for message in thread.get("messages", []):
        if message.get("ts") == ts:
            return message
    return None


async def room_slug(client: SlackClient, room_id: str) -> str:
    room = client._rooms.get(room_id)
    return room.name if room and room.name else room_id


async def room_context(client: SlackClient, room_id: str, username: str) -> str:
    room = client._rooms.get(room_id)
    topic = ""
    purpose = ""
    if not room:
        try:
            result = await client._api_get(
                "conversations.info", params={"channel": room_id}
            )
        except httpx.HTTPError:
            return ""
        convo = result.get("channel", {})
        room = RoomInfo(
            room_id=room_id,
            kind=conversation_kind(convo),
            members=[],
            name=convo.get("name", ""),
        )
        client._rooms[room_id] = room
        topic = convo.get("topic", {}).get("value", "")
        purpose = convo.get("purpose", {}).get("value", "")

    if room.kind is RoomKind.direct:
        return f"Room: DM with @{username}"

    label = room.name or room_id
    visibility = "private" if room.kind is RoomKind.private else "public"
    parts = [f"Room: #{label} ({visibility})"]
    if topic:
        parts.append(f"Topic: {topic}")
    if purpose:
        parts.append(f"Purpose: {purpose}")
    return "\n".join(parts)


async def prime_history(
    client: SlackClient,
    on_history: OnHistoryCallback | None,
    since: datetime | None = None,
) -> None:
    if not on_history:
        return
    try:
        rooms = await client.list_rooms()
    except httpx.HTTPError:
        log.warning("Failed to list Slack rooms for history", exc_info=True)
        return
    for room in (r for r in rooms if r.kind.is_dm):
        try:
            messages = await client.fetch_messages(room.room_id, after=since)
        except httpx.HTTPError:
            log.warning("Failed to fetch history for %s", room.room_id, exc_info=True)
            continue
        if not messages:
            continue
        await on_history(room, messages)
        for msg in messages:
            if client._high_water is None or msg.timestamp > client._high_water:
                client._high_water = msg.timestamp
