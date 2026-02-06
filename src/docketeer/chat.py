"""Rocket Chat client combining DDP subscriptions with async REST API."""

import asyncio
import logging
import mimetypes
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from docketeer.ddp import DDPClient

log = logging.getLogger(__name__)


@dataclass
class Attachment:
    url: str
    media_type: str
    title: str = ""


@dataclass
class IncomingMessage:
    message_id: str
    user_id: str
    username: str
    display_name: str
    text: str
    room_id: str
    is_direct: bool
    timestamp: datetime | None = None
    attachments: list[Attachment] | None = None


def _parse_rc_timestamp(ts: Any) -> datetime | None:
    """Parse a Rocket Chat timestamp into a datetime."""
    if isinstance(ts, dict) and "$date" in ts:
        return datetime.fromtimestamp(ts["$date"] / 1000, tz=timezone.utc)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
    return None


class RocketClient:
    """Hybrid Rocket Chat client: DDP for subscriptions, async REST for actions."""

    def __init__(self, url: str, username: str, password: str):
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self._ddp: DDPClient | None = None
        self._http: httpx.AsyncClient | None = None
        self._user_id: str | None = None

    async def connect(self) -> None:
        """Connect via DDP and authenticate via REST."""
        ws_url = self._to_ws_url(self.url)
        self._ddp = DDPClient(url=ws_url)
        await self._ddp.connect()

        self._http = httpx.AsyncClient(base_url=f"{self.url}/api/v1", timeout=30)

        # Authenticate via REST
        resp = await self._http.post("/login", json={
            "user": self.username, "password": self.password,
        })
        resp.raise_for_status()
        data = resp.json()["data"]
        auth_token = data["authToken"]
        self._user_id = data["userId"]
        self._http.headers.update({
            "X-Auth-Token": auth_token,
            "X-User-Id": self._user_id,
        })

        me = await self._get("me")
        log.info("Logged in as @%s (%s)", me.get("username"), me.get("name", ""))

        await self._ddp.call(
            "login",
            [{"user": {"username": self.username}, "password": self.password}],
        )

    def _to_ws_url(self, url: str) -> str:
        if url.startswith("https://"):
            return url.replace("https://", "wss://") + "/websocket"
        elif url.startswith("http://"):
            return url.replace("http://", "ws://") + "/websocket"
        return url + "/websocket"

    async def _get(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """GET an API endpoint, returning the parsed JSON."""
        resp = await self._http.get(f"/{endpoint}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, endpoint: str, **json_body: Any) -> dict[str, Any]:
        """POST to an API endpoint with a JSON body."""
        resp = await self._http.post(f"/{endpoint}", json=json_body)
        resp.raise_for_status()
        return resp.json()

    async def subscribe_to_my_messages(self) -> None:
        """Subscribe to all messages for the logged-in user."""
        if self._ddp and self._user_id:
            await self._ddp.subscribe(
                "stream-notify-user", [f"{self._user_id}/notification", False]
            )

    async def send_message(
        self, room_id: str, text: str, attachments: list[dict[str, Any]] | None = None
    ) -> None:
        """Send a message to a room."""
        body: dict[str, Any] = {"roomId": room_id, "text": text}
        if attachments:
            body["attachments"] = attachments
        await self._post("chat.postMessage", **body)

    async def upload_file(self, room_id: str, file_path: str, message: str = "") -> None:
        """Upload a file to a room and post it as a chat message."""
        path = Path(file_path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        resp = await self._http.post(
            f"/rooms.media/{room_id}",
            files={"file": (path.name, path.read_bytes(), content_type)},
        )
        resp.raise_for_status()
        file_id = resp.json()["file"]["_id"]
        await self._post(f"rooms.mediaConfirm/{room_id}/{file_id}", msg=message)

    async def fetch_attachment(self, url: str) -> bytes:
        """Fetch an attachment from Rocket Chat."""
        full_url = f"{self.url}{url}" if url.startswith("/") else url
        resp = await self._http.get(full_url)
        resp.raise_for_status()
        return resp.content

    async def fetch_message(self, message_id: str) -> dict[str, Any] | None:
        """Fetch a message by ID."""
        try:
            result = await self._get("chat.getMessage", msgId=message_id)
            return result.get("message")
        except Exception as e:
            log.warning("Failed to fetch message %s: %s", message_id, e)
            return None

    async def fetch_room_history(self, room_id: str, count: int = 20) -> list[dict[str, Any]]:
        """Fetch recent messages from a room."""
        try:
            result = await self._get("dm.history", roomId=room_id, count=count)
            messages = result.get("messages", [])
            return list(reversed(messages))
        except Exception as e:
            log.warning("Failed to fetch room history for %s: %s", room_id, e)
            return []

    async def list_dm_rooms(self) -> list[dict[str, Any]]:
        """List all DM rooms for the bot."""
        try:
            result = await self._get("dm.list")
            return result.get("ims", [])
        except Exception as e:
            log.warning("Failed to list DM rooms: %s", e)
            return []

    async def set_status(self, status: str, message: str = "") -> None:
        """Set the bot's presence status (online, busy, away, offline)."""
        delay = 1
        for attempt in range(4):
            try:
                await self._post("users.setStatus", status=status, message=message)
                return
            except Exception as e:
                if attempt == 3:
                    log.warning("Failed to set status to %s after retries: %s", status, e)
                    return
                log.debug("Status %s rate-limited, retrying in %ds", status, delay)
                await asyncio.sleep(delay)
                delay *= 2

    async def incoming_messages(self) -> AsyncIterator[IncomingMessage]:
        """Yield incoming messages from subscriptions."""
        if not self._ddp:
            return

        seen: set[str] = set()
        async for event in self._ddp.events():
            log.debug("DDP event: %s", event)
            msg = await self._parse_message_event(event)
            if not msg or msg.user_id == self._user_id or not (msg.text or msg.attachments):
                continue
            if msg.message_id in seen:
                log.debug("Skipping duplicate message %s", msg.message_id)
                continue
            seen.add(msg.message_id)
            log.info("Message from %s in %s", msg.username, msg.room_id)
            yield msg

    async def _parse_message_event(self, event: dict[str, Any]) -> IncomingMessage | None:
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
        user = msg_data.get("u", {}) or msg_data.get("sender", {}) or payload.get("sender", {})
        room_id = msg_data.get("rid", "") or payload.get("rid", "")
        text = msg_data.get("msg", "")

        attachments = None
        if raw_attachments := msg_data.get("attachments"):
            attachments = []
            for att in raw_attachments:
                if image_url := att.get("image_url"):
                    attachments.append(Attachment(
                        url=image_url,
                        media_type=att.get("image_type", "image/png"),
                        title=att.get("title", ""),
                    ))

        return IncomingMessage(
            message_id=message_id,
            user_id=user.get("_id", ""),
            username=user.get("username", ""),
            display_name=user.get("name", user.get("username", "")),
            text=text,
            room_id=room_id,
            is_direct=room_id.startswith(self._user_id or "") if room_id else False,
            timestamp=_parse_rc_timestamp(msg_data.get("ts")),
            attachments=attachments,
        )

    async def close(self) -> None:
        """Close the connection."""
        if self._http:
            await self._http.aclose()
        if self._ddp:
            await self._ddp.close()
