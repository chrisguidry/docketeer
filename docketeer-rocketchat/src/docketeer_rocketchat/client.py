"""Rocket Chat client combining DDP subscriptions with async REST API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import mimetypes
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from docketeer.chat import (
    ChatClient,
    IncomingMessage,
    OnHistoryCallback,
    RoomInfo,
    RoomKind,
    RoomMessage,
)
from docketeer_rocketchat.ddp import DDPClient
from docketeer_rocketchat.parsing import parse_attachments, parse_rc_timestamp
from docketeer_rocketchat.room_context import build_room_context

log = logging.getLogger(__name__)


class RocketChatClient(ChatClient):
    """Hybrid Rocket Chat client: DDP for subscriptions, async REST for actions."""

    def __init__(self) -> None:
        from docketeer import environment

        self.url = environment.get_str("ROCKETCHAT_URL").rstrip("/")
        self.username = environment.get_str("ROCKETCHAT_USERNAME")
        self.password = environment.get_str("ROCKETCHAT_PASSWORD")
        self._ddp: DDPClient | None = None
        self._http: httpx.AsyncClient | None = None
        self._conn_stack: AsyncExitStack | None = None
        self._user_id: str | None = None
        self._room_kinds: dict[str, RoomKind] = {}
        self._high_water: datetime | None = None

    @property
    def user_id(self) -> str:
        return self._user_id or ""

    async def __aenter__(self) -> RocketChatClient:
        await self._open_connections()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._close_connections()

    async def _open_connections(self) -> None:
        log.info("Connecting to Rocket Chat at %s...", self.url)
        ws_url = self._to_ws_url(self.url)

        stack = AsyncExitStack()
        self._ddp = await stack.enter_async_context(DDPClient(url=ws_url))
        self._http = httpx.AsyncClient(base_url=f"{self.url}/api/v1", timeout=30)
        stack.push_async_callback(self._http.aclose)
        self._conn_stack = stack

        # Authenticate via REST
        resp = await self._http.post(
            "/login",
            json={
                "user": self.username,
                "password": self.password,
            },
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        auth_token = data["authToken"]
        self._user_id = data["userId"]
        self._http.headers["X-Auth-Token"] = auth_token
        self._http.headers["X-User-Id"] = self._user_id

        me = await self._get("me")
        log.info("Logged in as @%s (%s)", me.get("username"), me.get("name", ""))

        await self._ddp.call(
            "login",
            [{"user": {"username": self.username}, "password": self.password}],
        )

    async def _close_connections(self) -> None:
        if self._conn_stack:
            await self._conn_stack.aclose()
            self._conn_stack = None
        self._ddp = None
        self._http = None

    @property
    def _api(self) -> httpx.AsyncClient:
        assert self._http is not None, "Not connected — call connect() first"
        return self._http

    @staticmethod
    def _to_ws_url(url: str) -> str:
        for http, ws in [("https://", "wss://"), ("http://", "ws://")]:
            if url.startswith(http):
                return url.replace(http, ws) + "/websocket"
        return url + "/websocket"

    async def _get(self, endpoint: str, **params: Any) -> dict[str, Any]:
        resp = await self._api.get(f"/{endpoint}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, endpoint: str, **json_body: Any) -> dict[str, Any]:
        resp = await self._api.post(f"/{endpoint}", json=json_body)
        resp.raise_for_status()
        return resp.json()

    async def subscribe_to_my_messages(self) -> None:
        if self._ddp and self._user_id:
            await self._ddp.subscribe(
                "stream-notify-user", [f"{self._user_id}/notification", False]
            )

    async def send_message(
        self,
        room_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        *,
        thread_id: str = "",
    ) -> None:
        body: dict[str, Any] = {"roomId": room_id, "text": text}
        if attachments:
            body["attachments"] = attachments
        if thread_id:
            body["tmid"] = thread_id
        await self._post("chat.postMessage", **body)

    async def upload_file(
        self, room_id: str, file_path: str, message: str = "", *, thread_id: str = ""
    ) -> None:
        path = Path(file_path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        resp = await self._api.post(
            f"/rooms.media/{room_id}",
            files={"file": (path.name, path.read_bytes(), content_type)},
        )
        resp.raise_for_status()
        file_id = resp.json()["file"]["_id"]
        confirm_body: dict[str, Any] = {"msg": message}
        if thread_id:
            confirm_body["tmid"] = thread_id
        await self._post(f"rooms.mediaConfirm/{room_id}/{file_id}", **confirm_body)

    async def fetch_attachment(self, url: str) -> bytes:
        full_url = f"{self.url}{url}" if url.startswith("/") else url
        resp = await self._api.get(full_url)
        resp.raise_for_status()
        return resp.content

    async def fetch_message(self, message_id: str) -> dict[str, Any] | None:
        try:
            result = await self._get("chat.getMessage", msgId=message_id)
            return result.get("message")
        except Exception as e:
            log.warning("Failed to fetch message %s: %s", message_id, e)
            return None

    async def fetch_messages(
        self,
        room_id: str,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        count: int = 50,
    ) -> list[RoomMessage]:
        try:
            params: dict[str, Any] = {"roomId": room_id, "count": count}
            if after:
                params["oldest"] = after.isoformat()
            if before:
                params["latest"] = before.isoformat()

            kind = self._room_kinds.get(room_id)
            match kind:
                case RoomKind.public:
                    endpoint = "channels.history"
                case RoomKind.private:
                    endpoint = "groups.history"
                case _:
                    endpoint = "dm.history"

            result = await self._get(endpoint, **params)
            raw_messages = list(reversed(result.get("messages", [])))
        except Exception as e:
            log.warning("Failed to fetch messages for %s: %s", room_id, e)
            return []

        messages: list[RoomMessage] = []
        for msg in raw_messages:
            if msg.get("t"):
                continue
            text = msg.get("msg", "")
            user = msg.get("u", {})
            dt = parse_rc_timestamp(msg.get("ts"))
            if not dt:
                continue

            raw_att = msg.get("attachments")
            attachments = parse_attachments(raw_att) if raw_att else None

            messages.append(
                RoomMessage(
                    message_id=msg.get("_id", ""),
                    timestamp=dt,
                    username=user.get("username", "unknown"),
                    display_name=user.get("name", user.get("username", "unknown")),
                    text=text,
                    attachments=attachments,
                    thread_id=msg.get("tmid", ""),
                )
            )
        return messages

    async def list_rooms(self) -> list[RoomInfo]:
        """List all rooms the bot is a member of."""
        rooms: list[RoomInfo] = []

        try:
            result = await self._get("dm.list")
            for dm in result.get("ims", []):
                room_id = dm.get("_id", "")
                usernames = dm.get("usernames", [])
                kind = RoomKind.group if len(usernames) > 2 else RoomKind.direct
                self._room_kinds[room_id] = kind
                rooms.append(
                    RoomInfo(
                        room_id=room_id,
                        kind=kind,
                        members=usernames,
                    )
                )
        except Exception as e:
            log.warning("Failed to list DM rooms: %s", e)

        try:
            result = await self._get("channels.list.joined")
            for ch in result.get("channels", []):
                room_id = ch.get("_id", "")
                self._room_kinds[room_id] = RoomKind.public
                rooms.append(
                    RoomInfo(
                        room_id=room_id,
                        kind=RoomKind.public,
                        members=ch.get("usernames", []),
                        name=ch.get("name", ""),
                    )
                )
        except Exception as e:
            log.warning("Failed to list channels: %s", e)

        try:
            result = await self._get("groups.list")
            for grp in result.get("groups", []):
                room_id = grp.get("_id", "")
                self._room_kinds[room_id] = RoomKind.private
                rooms.append(
                    RoomInfo(
                        room_id=room_id,
                        kind=RoomKind.private,
                        members=grp.get("usernames", []),
                        name=grp.get("name", ""),
                    )
                )
        except Exception as e:
            log.warning("Failed to list groups: %s", e)

        return rooms

    async def set_status(self, status: str, message: str = "") -> None:
        """Set the bot's presence status (online, busy, away, offline)."""
        delay = 1
        for attempt in range(4):  # pragma: no branch
            try:
                await self._post("users.setStatus", status=status, message=message)
                return
            except Exception as e:
                if attempt == 3:
                    log.warning(
                        "Failed to set status to %s after retries: %s", status, e
                    )
                    return
                log.debug("Status %s rate-limited, retrying in %ds", status, delay)
                await asyncio.sleep(delay)
                delay *= 2

    async def react(self, message_id: str, emoji: str) -> None:
        await self._post(
            "chat.react", messageId=message_id, emoji=emoji, shouldReact=True
        )

    async def unreact(self, message_id: str, emoji: str) -> None:
        await self._post(
            "chat.react", messageId=message_id, emoji=emoji, shouldReact=False
        )

    async def send_typing(self, room_id: str, typing: bool) -> None:
        """Send a typing indicator to a room via the user-activity stream."""
        if not self._ddp:
            return
        activities = ["user-typing"] if typing else []
        try:
            await self._ddp.call(
                "stream-notify-room",
                [f"{room_id}/user-activity", self.username, activities, {}],
            )
        except Exception:
            log.warning("Failed to send typing indicator to %s", room_id)

    async def room_context(self, room_id: str, username: str) -> str:
        """Return rich room context from the RC API."""
        kind = self._room_kinds.get(room_id)
        return await build_room_context(
            self._get, self.username, room_id, username, kind
        )

    async def incoming_messages(
        self,
        on_history: OnHistoryCallback | None = None,
    ) -> AsyncGenerator[IncomingMessage, None]:
        """Yield incoming messages, reconnecting with backoff on disconnect."""
        if not self._ddp:
            return

        seen: set[str] = set()
        backoff = 1

        while True:
            await self._after_connect(on_history, since=self._high_water)

            async for event in self._ddp.events():
                log.debug("DDP event: %s", event)
                msg = await self._parse_message_event(event)
                if (
                    not msg
                    or msg.user_id == self._user_id
                    or not (msg.text or msg.attachments)
                ):
                    continue
                if msg.message_id in seen:
                    log.debug("Skipping duplicate message %s", msg.message_id)
                    continue
                seen.add(msg.message_id)
                log.info("Message from %s in %s", msg.username, msg.room_id)
                if msg.timestamp and (
                    self._high_water is None or msg.timestamp > self._high_water
                ):
                    self._high_water = msg.timestamp
                yield msg

            log.warning("Connection lost, reconnecting...")
            while True:
                with contextlib.suppress(Exception):
                    await self._close_connections()
                await asyncio.sleep(backoff)
                try:
                    await self._open_connections()
                    backoff = 1
                    break
                except Exception:
                    backoff = min(backoff * 2, 60)
                    log.exception("Reconnect failed, next attempt in %ds", backoff)

    async def _after_connect(
        self,
        on_history: OnHistoryCallback | None,
        since: datetime | None = None,
    ) -> None:
        """Subscribe, set status, and prime history after a successful connect."""
        await self.subscribe_to_my_messages()
        await self.set_status("online")
        await self._prime_history(on_history, since=since)

    async def _prime_history(
        self,
        on_history: OnHistoryCallback | None,
        since: datetime | None = None,
    ) -> None:
        """Fetch room history and prime the brain via callback."""
        if not on_history:
            return

        try:
            rooms = await self.list_rooms()
        except Exception:
            log.warning("Failed to list rooms for history", exc_info=True)
            return

        dm_rooms = [
            r
            for r in rooms
            if r.kind.is_dm and any(m != self.username for m in r.members)
        ]

        qualifier = f" since {since.isoformat()}" if since else ""
        log.info("Loading history for %d room(s)%s", len(dm_rooms), qualifier)

        for room in dm_rooms:
            try:
                messages = await self.fetch_messages(room.room_id, after=since)
                if not messages:
                    continue
                await on_history(room, messages)
                for msg in messages:
                    if self._high_water is None or msg.timestamp > self._high_water:
                        self._high_water = msg.timestamp
                others = [m for m in room.members if m != self.username]
                log.info(
                    "  %s with %s: %d messages",
                    room.kind.value,
                    ", ".join(others) or room.room_id,
                    len(messages),
                )
            except Exception:
                log.warning(
                    "Failed to load history for %s", room.room_id, exc_info=True
                )

    async def _parse_message_event(
        self, event: dict[str, Any]
    ) -> IncomingMessage | None:
        """Parse a DDP event into an IncomingMessage."""
        if event.get("msg") != "changed":
            return None

        fields = event.get("fields", {})
        args = fields.get("args", [])
        if not args:
            return None

        msg_data = args[0]
        if not isinstance(msg_data, dict):
            return None

        if msg_data.get("t"):
            return None

        # Check if this is a notification that needs full message fetch
        payload = msg_data.get("payload", {})
        if payload and payload.get("_id"):
            full_msg = await self.fetch_message(payload["_id"])
            if full_msg:
                msg_data = full_msg

        message_id = msg_data.get("_id", "") or payload.get("_id", "")
        user = (
            msg_data.get("u", {})
            or msg_data.get("sender", {})
            or payload.get("sender", {})
        )
        room_id = msg_data.get("rid", "") or payload.get("rid", "")
        text = msg_data.get("msg", "")

        raw_att = msg_data.get("attachments")
        attachments = parse_attachments(raw_att) if raw_att else None

        kind = self._room_kinds.get(room_id, RoomKind.direct)

        return IncomingMessage(
            message_id=message_id,
            user_id=user.get("_id", ""),
            username=user.get("username", ""),
            display_name=user.get("name", user.get("username", "")),
            text=text,
            room_id=room_id,
            kind=kind,
            timestamp=parse_rc_timestamp(msg_data.get("ts")),
            attachments=attachments,
            thread_id=msg_data.get("tmid", ""),
        )
