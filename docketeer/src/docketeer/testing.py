"""In-memory test doubles — no network, full control."""

import asyncio
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from docketeer.chat import ChatClient, IncomingMessage, RoomMessage
from docketeer.vault import SecretReference, Vault


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


@dataclass
class Reaction:
    message_id: str
    emoji: str
    action: str  # "react" or "unreact"


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
        self.typing_events: list[tuple[str, bool]] = []
        self.reactions: list[Reaction] = []
        self._incoming: asyncio.Queue[IncomingMessage | None] = asyncio.Queue()
        self._room_messages: dict[str, list[RoomMessage]] = {}
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

    async def fetch_messages(
        self,
        room_id: str,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        count: int = 50,
    ) -> list[RoomMessage]:
        messages = self._room_messages.get(room_id, [])
        if after:
            messages = [m for m in messages if m.timestamp > after]
        if before:
            messages = [m for m in messages if m.timestamp < before]
        return messages[:count]

    async def list_dm_rooms(self) -> list[dict[str, Any]]:
        return self._dm_rooms

    async def set_status(self, status: str, message: str = "") -> None:
        self.status_changes.append((status, message))

    async def send_typing(self, room_id: str, typing: bool) -> None:
        self.typing_events.append((room_id, typing))

    async def react(self, message_id: str, emoji: str) -> None:
        self.reactions.append(Reaction(message_id, emoji, "react"))

    async def unreact(self, message_id: str, emoji: str) -> None:
        self.reactions.append(Reaction(message_id, emoji, "unreact"))


class MemoryVault(Vault):
    """In-memory Vault for tests — no external service needed."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._secrets: dict[str, str] = dict(initial) if initial else {}

    async def list(self) -> list[SecretReference]:
        return [SecretReference(name=name) for name in self._secrets]

    async def resolve(self, name: str) -> str:
        if name not in self._secrets:
            raise KeyError(name)
        return self._secrets[name]

    async def store(self, name: str, value: str) -> None:
        self._secrets[name] = value

    async def generate(self, name: str, length: int = 32) -> None:
        self._secrets[name] = secrets.token_urlsafe(length)[:length]

    async def delete(self, name: str) -> None:
        if name not in self._secrets:
            raise KeyError(name)
        del self._secrets[name]
