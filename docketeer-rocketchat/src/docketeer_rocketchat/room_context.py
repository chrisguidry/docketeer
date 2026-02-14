"""Room context rendering for Rocket Chat API."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from docketeer.chat import RoomKind

log = logging.getLogger(__name__)

type GetFn = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


async def build_room_context(
    get: GetFn,
    bot_username: str,
    room_id: str,
    username: str,
    kind: RoomKind | None,
) -> str:
    """Build rich room context from the RC API, with fallback on errors."""
    try:
        return await _build(get, bot_username, room_id, username, kind)
    except Exception:
        log.warning("Failed to build room context for %s", room_id, exc_info=True)
        return fallback_room_context(room_id, username, kind)


async def _build(
    get: GetFn,
    bot_username: str,
    room_id: str,
    username: str,
    kind: RoomKind | None,
) -> str:
    match kind:
        case RoomKind.direct:
            return await _dm_context(get, username)
        case RoomKind.group:
            return await _group_dm_context(get, bot_username, room_id, username)
        case RoomKind.public | RoomKind.private:
            return await _channel_context(get, bot_username, room_id, kind)
        case _:
            return f"Room: DM with @{username}"


async def _dm_context(get: GetFn, username: str) -> str:
    try:
        data = await get("users.info", username=username)
        user = data.get("user", {})
        display_name = user.get("name", username)
        status = user.get("status", "offline")
        return f"Room: DM with {display_name} (@{username}, {status})"
    except Exception:
        return f"Room: DM with @{username}"


async def _group_dm_context(
    get: GetFn, bot_username: str, room_id: str, username: str
) -> str:
    try:
        data = await get("dm.members", roomId=room_id)
        members = data.get("members", [])
        others = [m for m in members if m.get("username") != bot_username]
        parts = []
        for m in others:
            name = m.get("name", m.get("username", "?"))
            uname = m.get("username", "?")
            status = m.get("status", "offline")
            parts.append(f"{name} (@{uname}, {status})")
        return f"Room: group DM with {', '.join(parts)}" if parts else "Room: group DM"
    except Exception:
        return f"Room: group DM with @{username}"


async def _channel_context(
    get: GetFn, bot_username: str, room_id: str, kind: RoomKind
) -> str:
    endpoint = "channels.info" if kind is RoomKind.public else "groups.info"
    data = await get(endpoint, roomId=room_id)
    ch = data.get("channel", data.get("group", {}))
    name = ch.get("name", "")
    topic = ch.get("topic", "")
    description = ch.get("description", "")
    member_count = ch.get("usersCount", 0)
    visibility = "private" if kind is RoomKind.private else "public"

    parts = [f"Room: #{name} ({visibility}, {member_count} members)"]
    if topic:
        parts.append(f"Topic: {topic}")
    if description:
        parts.append(f"Description: {description}")

    try:
        members_data = await get(
            "channels.members" if kind is RoomKind.public else "groups.members",
            roomId=room_id,
            count=20,
        )
        online = [
            f"{m.get('name', m.get('username', '?'))} (@{m.get('username', '?')})"
            for m in members_data.get("members", [])
            if m.get("status") == "online" and m.get("username") != bot_username
        ]
        if online:
            parts.append(f"Online: {', '.join(online)}")
    except Exception:
        log.debug("Failed to fetch channel members for %s", room_id, exc_info=True)

    return "\n".join(parts)


def fallback_room_context(room_id: str, username: str, kind: RoomKind | None) -> str:
    match kind:
        case RoomKind.direct:
            return f"Room: DM with @{username}"
        case RoomKind.group:
            return f"Room: group DM with @{username}"
        case _:
            return ""
