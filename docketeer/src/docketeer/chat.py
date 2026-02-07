"""Chat client interface for the Docketeer agent."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from docketeer.prompt import HistoryMessage


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


class ChatClient(ABC):
    """Abstract chat client interface for testing and alternative backends."""

    username: str
    user_id: str

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def subscribe_to_my_messages(self) -> None: ...

    @abstractmethod
    def incoming_messages(self) -> AsyncGenerator[IncomingMessage, None]: ...

    @abstractmethod
    async def send_message(
        self, room_id: str, text: str, attachments: list[dict[str, Any]] | None = None
    ) -> None: ...

    @abstractmethod
    async def upload_file(
        self, room_id: str, file_path: str, message: str = ""
    ) -> None: ...

    @abstractmethod
    async def fetch_attachment(self, url: str) -> bytes: ...

    @abstractmethod
    async def fetch_message(self, message_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def fetch_room_history(
        self, room_id: str, count: int = 20
    ) -> list[dict[str, Any]]: ...

    async def fetch_history_as_messages(
        self, room_id: str, count: int = 20
    ) -> list[HistoryMessage]:
        """Fetch room history as HistoryMessage objects for the brain."""
        return []

    @abstractmethod
    async def list_dm_rooms(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def set_status(self, status: str, message: str = "") -> None: ...

    async def set_status_busy(self) -> None:
        """Signal that the bot is busy (e.g. executing tools)."""
        await self.set_status("away")

    async def set_status_available(self) -> None:
        """Signal that the bot is idle and ready."""
        await self.set_status("online")

    @abstractmethod
    async def send_typing(self, room_id: str, typing: bool) -> None: ...
