"""Rocket Chat client combining DDP subscriptions with REST API."""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from rocketchat_API.rocketchat import RocketChat

from docketeer.ddp import DDPClient

log = logging.getLogger(__name__)


@dataclass
class Attachment:
    url: str
    media_type: str
    title: str = ""


@dataclass
class IncomingMessage:
    user_id: str
    username: str
    display_name: str
    text: str
    room_id: str
    is_direct: bool
    attachments: list[Attachment] | None = None


class RocketClient:
    """Hybrid Rocket Chat client: DDP for subscriptions, REST for actions."""

    def __init__(self, url: str, username: str, password: str):
        self.url = url
        self.username = username
        self.password = password
        self._ddp: DDPClient | None = None
        self._rest: RocketChat | None = None
        self._user_id: str | None = None
        self._subscribed_rooms: set[str] = set()

    async def connect(self) -> None:
        """Connect via DDP and authenticate via REST."""
        ws_url = self._to_ws_url(self.url)
        self._ddp = DDPClient(url=ws_url)
        await self._ddp.connect()

        self._rest = RocketChat(
            self.username, self.password, server_url=self.url
        )
        me = self._rest.me()
        self._user_id = me["_id"]
        log.info("Logged in as @%s (%s)", me.get("username"), me.get("name", ""))

        await self._ddp.call(
            "login",
            [{"user": {"username": self.username}, "password": self.password}],
        )

    def _to_ws_url(self, url: str) -> str:
        url = url.rstrip("/")
        if url.startswith("https://"):
            return url.replace("https://", "wss://") + "/websocket"
        elif url.startswith("http://"):
            return url.replace("http://", "ws://") + "/websocket"
        return url + "/websocket"

    async def subscribe_to_room(self, room_id: str) -> None:
        """Subscribe to messages in a room."""
        if self._ddp and room_id not in self._subscribed_rooms:
            await self._ddp.subscribe("stream-room-messages", [room_id, False])
            self._subscribed_rooms.add(room_id)

    async def subscribe_to_my_messages(self) -> None:
        """Subscribe to all messages for the logged-in user."""
        if self._ddp and self._user_id:
            await self._ddp.subscribe(
                "stream-notify-user", [f"{self._user_id}/notification", False]
            )

    def send_message(
        self, room_id: str, text: str, attachments: list[dict[str, Any]] | None = None
    ) -> None:
        """Send a message to a room via REST API."""
        if self._rest:
            self._rest.chat_post_message(text, room_id=room_id, attachments=attachments)

    def fetch_attachment(self, url: str) -> bytes:
        """Fetch an attachment from Rocket Chat."""
        if not self._rest:
            raise RuntimeError("Not connected")
        full_url = f"{self.url}{url}" if url.startswith("/") else url
        response = self._rest.session.get(full_url, headers=self._rest.headers)
        response.raise_for_status()
        return response.content

    def fetch_message(self, message_id: str) -> dict[str, Any] | None:
        """Fetch a message by ID via REST API."""
        if not self._rest:
            return None
        try:
            result = self._rest.chat_get_message(msg_id=message_id)
            return result.get("message")
        except Exception as e:
            log.warning("Failed to fetch message %s: %s", message_id, e)
            return None

    def fetch_room_history(self, room_id: str, count: int = 20) -> list[dict[str, Any]]:
        """Fetch recent messages from a room."""
        if not self._rest:
            return []
        try:
            result = self._rest.call_api_get("dm.history", roomId=room_id, count=count)
            messages = result.get("messages", [])
            # Messages come newest-first, reverse to get chronological order
            return list(reversed(messages))
        except Exception as e:
            log.warning("Failed to fetch room history for %s: %s", room_id, e)
            return []

    def list_dm_rooms(self) -> list[dict[str, Any]]:
        """List all DM rooms for the bot."""
        if not self._rest:
            return []
        try:
            result = self._rest.call_api_get("dm.list")
            return result.get("ims", [])
        except Exception as e:
            log.warning("Failed to list DM rooms: %s", e)
            return []

    async def send_typing(self, room_id: str, typing: bool = True) -> None:
        """Send typing indicator via DDP."""
        if self._ddp:
            await self._ddp.call(
                "stream-notify-room",
                [f"{room_id}/typing", self.username, typing],
            )

    async def incoming_messages(self) -> AsyncIterator[IncomingMessage]:
        """Yield incoming messages from subscriptions."""
        if not self._ddp:
            return

        async for event in self._ddp.events():
            log.debug("DDP event: %s", event)
            msg = self._parse_message_event(event)
            if msg and msg.user_id != self._user_id and (msg.text or msg.attachments):
                log.info("Message from %s in %s", msg.username, msg.room_id)
                yield msg

    def _parse_message_event(self, event: dict[str, Any]) -> IncomingMessage | None:
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
            # This is a notification - fetch full message for attachments
            full_msg = self.fetch_message(payload["_id"])
            if full_msg:
                msg_data = full_msg

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
            user_id=user.get("_id", ""),
            username=user.get("username", ""),
            display_name=user.get("name", user.get("username", "")),
            text=text,
            room_id=room_id,
            is_direct=room_id.startswith(self._user_id or "") if room_id else False,
            attachments=attachments,
        )

    async def close(self) -> None:
        """Close the connection."""
        if self._ddp:
            await self._ddp.close()
