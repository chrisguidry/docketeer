"""Chat client interface for the Docketeer agent."""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from docketeer.plugins import discover_one

if TYPE_CHECKING:
    from docketeer.tools import ToolContext

log = logging.getLogger(__name__)


@dataclass
class Attachment:
    url: str
    media_type: str
    title: str = ""


@dataclass
class RoomMessage:
    """A message from room history, with full context and attachment references."""

    message_id: str
    timestamp: datetime
    username: str
    display_name: str
    text: str
    attachments: list[Attachment] | None = None


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
    async def fetch_messages(
        self,
        room_id: str,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        count: int = 50,
    ) -> list[RoomMessage]: ...

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


RegisterToolsFn = Callable[["ChatClient", "ToolContext"], None]


def _noop_register_tools(_client: "ChatClient", _ctx: "ToolContext") -> None:
    pass


def discover_chat_backend() -> tuple["ChatClient", RegisterToolsFn]:
    """Discover the chat backend via entry_points."""
    ep = discover_one("docketeer.chat", "CHAT")
    if ep is None:
        raise RuntimeError("No chat backend installed")
    module = ep.load()
    client = module.create_client()
    register_fn = getattr(module, "register_tools", _noop_register_tools)
    return client, register_fn
