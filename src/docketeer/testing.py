"""In-memory ChatClient for testing — no network, full control."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from docketeer.chat import ChatClient, IncomingMessage


@dataclass
class SentMessage:
    room_id: str
    text: str
    attachments: list[dict[str, Any]] | None = None


@dataclass
class UploadedFile:
    room_id: str
    file_path: str
    message: str = ""


class MemoryChat(ChatClient):
    """In-memory ChatClient for tests — no network, full control."""

    def __init__(
        self,
        username: str = "testbot",
        user_id: str = "bot123",
    ) -> None:
        self.username = username
        self.user_id = user_id
        self.connected = False
        self.closed = False
        self.subscribed = False
        self.sent_messages: list[SentMessage] = []
        self.uploaded_files: list[UploadedFile] = []
        self.status_changes: list[tuple[str, str]] = []
        self._incoming: asyncio.Queue[IncomingMessage | None] = asyncio.Queue()
        self._room_history: dict[str, list[dict[str, Any]]] = {}
        self._dm_rooms: list[dict[str, Any]] = []
        self._attachments: dict[str, bytes] = {}
        self._messages: dict[str, dict[str, Any]] = {}

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def subscribe_to_my_messages(self) -> None:
        self.subscribed = True

    async def incoming_messages(self) -> AsyncGenerator[IncomingMessage, None]:
        while True:
            msg = await self._incoming.get()
            if msg is None:
                break
            yield msg

    async def send_message(
        self,
        room_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        self.sent_messages.append(SentMessage(room_id, text, attachments))

    async def upload_file(
        self, room_id: str, file_path: str, message: str = ""
    ) -> None:
        self.uploaded_files.append(UploadedFile(room_id, file_path, message))

    async def fetch_attachment(self, url: str) -> bytes:
        if url in self._attachments:
            return self._attachments[url]
        raise ConnectionError(f"No canned attachment for {url}")

    async def fetch_message(self, message_id: str) -> dict[str, Any] | None:
        return self._messages.get(message_id)

    async def fetch_room_history(
        self, room_id: str, count: int = 20
    ) -> list[dict[str, Any]]:
        return self._room_history.get(room_id, [])[:count]

    async def list_dm_rooms(self) -> list[dict[str, Any]]:
        return self._dm_rooms

    async def set_status(self, status: str, message: str = "") -> None:
        self.status_changes.append((status, message))
