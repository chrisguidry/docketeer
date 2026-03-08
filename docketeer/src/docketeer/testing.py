"""In-memory test doubles — no network, full control."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from docketeer.antenna import Band, Signal, SignalFilter
from docketeer.chat import (
    ChatClient,
    IncomingMessage,
    OnHistoryCallback,
    RoomInfo,
    RoomMessage,
)
from docketeer.search import SearchCatalog, SearchIndex, SearchResult
from docketeer.vault import SecretReference, Vault


@dataclass
class SentMessage:
    room_id: str
    text: str
    attachments: list[dict[str, Any]] | None = None
    thread_id: str = ""


@dataclass
class UploadedFile:
    room_id: str
    file_path: str
    message: str = ""
    thread_id: str = ""


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
        self.sent_messages: list[SentMessage] = []
        self.uploaded_files: list[UploadedFile] = []
        self.status_changes: list[tuple[str, str]] = []
        self.typing_events: list[tuple[str, bool]] = []
        self.reactions: list[Reaction] = []
        self._incoming: asyncio.Queue[IncomingMessage | None] = asyncio.Queue()
        self._room_messages: dict[str, list[RoomMessage]] = {}
        self._rooms: list[RoomInfo] = []
        self._attachments: dict[str, bytes] = {}
        self._messages: dict[str, dict[str, Any]] = {}
        self._room_context: dict[str, str] = {}
        self._room_slugs: dict[str, str] = {}

    async def __aenter__(self) -> MemoryChat:
        self.connected = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.closed = True

    async def incoming_messages(
        self,
        on_history: OnHistoryCallback | None = None,
    ) -> AsyncGenerator[IncomingMessage, None]:
        if on_history:
            for room in self._rooms:
                messages = self._room_messages.get(room.room_id, [])
                if messages:
                    await on_history(room, messages)
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
        *,
        thread_id: str = "",
    ) -> None:
        self.sent_messages.append(SentMessage(room_id, text, attachments, thread_id))
        if self._on_message_sent:
            await self._on_message_sent(room_id, text)

    async def upload_file(
        self, room_id: str, file_path: str, message: str = "", *, thread_id: str = ""
    ) -> None:
        self.uploaded_files.append(UploadedFile(room_id, file_path, message, thread_id))

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

    async def list_rooms(self) -> list[RoomInfo]:
        return self._rooms

    async def set_status(self, status: str, message: str = "") -> None:
        self.status_changes.append((status, message))

    async def send_typing(self, room_id: str, typing: bool) -> None:
        self.typing_events.append((room_id, typing))

    async def react(self, message_id: str, emoji: str) -> None:
        self.reactions.append(Reaction(message_id, emoji, "react"))

    async def unreact(self, message_id: str, emoji: str) -> None:
        self.reactions.append(Reaction(message_id, emoji, "unreact"))

    async def room_slug(self, room_id: str) -> str:
        if room_id in self._room_slugs:
            return self._room_slugs[room_id]
        return await super().room_slug(room_id)

    async def room_context(self, room_id: str, username: str) -> str:
        if room_id in self._room_context:
            return self._room_context[room_id]
        return await super().room_context(room_id, username)


class MemorySearch(SearchIndex):
    """In-memory SearchIndex for tests — no embedding model needed."""

    def __init__(self) -> None:
        self._documents: dict[str, str] = {}

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        results = []
        query_lower = query.lower()
        for path, content in self._documents.items():
            if query_lower in content.lower():
                snippet = content[:200]
                results.append(SearchResult(path=path, score=1.0, snippet=snippet))
        return results[:limit]

    async def index(self, path: str, content: str) -> None:
        self._documents[path] = content

    async def deindex(self, path: str) -> None:
        self._documents.pop(path, None)


class MemoryCatalog(SearchCatalog):
    """In-memory SearchCatalog for tests."""

    def __init__(self) -> None:
        self._indices: dict[str, MemorySearch] = {}

    def get_index(self, name: str) -> MemorySearch:
        if name not in self._indices:
            self._indices[name] = MemorySearch()
        return self._indices[name]


class MemoryVault(Vault):
    """In-memory Vault for tests — no external service needed."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._secrets: dict[str, str] = dict(initial) if initial else {}

    async def list_secrets(self) -> list[SecretReference]:
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


class MemoryWatcher:
    """In-memory WorkspaceWatcher for tests — no filesystem watching."""

    def __init__(self) -> None:
        self._pending: set[str] = set()
        self._initialized: set[str] = set()

    async def __aenter__(self) -> MemoryWatcher:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass

    def notify(self, *paths: str) -> None:
        """Simulate external file changes."""
        self._pending.update(paths)

    def drain(self, line: str) -> set[str]:
        if line not in self._initialized:
            self._initialized.add(line)
            return set()
        result = set(self._pending)
        self._pending.clear()
        return result


class MemoryBand(Band):
    """In-memory Band for tests — push signals directly."""

    def __init__(self, name: str = "memory") -> None:
        self.name = name
        self._queue: asyncio.Queue[Signal | None] = asyncio.Queue()
        self.last_secret: str | None = None

    async def __aenter__(self) -> MemoryBand:
        return self

    async def __aexit__(self, *exc: object) -> None:
        pass

    def emit(self, signal: Signal) -> None:
        """Push a signal from test code."""
        self._queue.put_nowait(signal)

    def stop(self) -> None:
        """Signal the listener to stop."""
        self._queue.put_nowait(None)

    async def listen(
        self,
        topic: str,
        filters: list[SignalFilter],
        last_signal_id: str = "",
        secret: str | None = None,
    ) -> AsyncGenerator[Signal, None]:
        self.last_secret = secret
        while True:
            signal = await self._queue.get()
            if signal is None:
                break
            yield signal
