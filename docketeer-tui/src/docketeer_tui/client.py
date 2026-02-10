"""Terminal chat client for local development."""

import asyncio
import logging
import secrets
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from docketeer.chat import ChatClient, IncomingMessage, RoomMessage

log = logging.getLogger(__name__)

ROOM_ID = "terminal"
USER_ID = "local-user"
USERNAME = "you"


class TUIClient(ChatClient):
    """Chat client that reads from stdin and writes to the terminal."""

    username = "docketeer"
    user_id = "docketeer-tui"

    def __init__(self) -> None:
        self._console = Console()
        self._messages: list[RoomMessage] = []
        self._closed = False

    async def connect(self) -> None:
        self._console.print()
        self._console.rule("[bold]docketeer[/bold]")
        self._console.print("  type a message and press enter. ctrl-c to quit.\n")

    async def close(self) -> None:
        self._closed = True
        self._console.print()
        self._console.rule("[dim]disconnected[/dim]")

    async def subscribe_to_my_messages(self) -> None:
        pass

    async def incoming_messages(self) -> AsyncGenerator[IncomingMessage, None]:
        loop = asyncio.get_running_loop()
        while not self._closed:
            try:
                text = await loop.run_in_executor(None, self._read_input)
            except (EOFError, KeyboardInterrupt):
                break
            if text is None:
                break
            text = text.strip()
            if not text:
                continue

            now = datetime.now(UTC)
            msg_id = secrets.token_hex(8)

            self._messages.append(
                RoomMessage(
                    message_id=msg_id,
                    timestamp=now,
                    username=USERNAME,
                    display_name=USERNAME,
                    text=text,
                )
            )

            yield IncomingMessage(
                message_id=msg_id,
                user_id=USER_ID,
                username=USERNAME,
                display_name=USERNAME,
                text=text,
                room_id=ROOM_ID,
                is_direct=True,
                timestamp=now,
            )

    def _read_input(self) -> str | None:
        """Blocking stdin read, run in executor."""
        try:
            return input()
        except EOFError:
            return None

    async def send_message(
        self,
        room_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        *,
        thread_id: str = "",
    ) -> None:
        now = datetime.now(UTC)
        msg_id = secrets.token_hex(8)
        self._messages.append(
            RoomMessage(
                message_id=msg_id,
                timestamp=now,
                username=self.username,
                display_name=self.username,
                text=text,
            )
        )
        self._console.print()
        self._console.print(Markdown(text))
        self._console.print()

    async def upload_file(
        self, room_id: str, file_path: str, message: str = "", *, thread_id: str = ""
    ) -> None:
        label = Text(f"  [file: {file_path}]", style="dim")
        if message:
            self._console.print(f"\n{message}")
        self._console.print(label)
        self._console.print()

    async def fetch_attachment(self, url: str) -> bytes:
        raise ConnectionError(f"TUI client cannot fetch attachments: {url}")

    async def fetch_message(self, message_id: str) -> dict[str, Any] | None:
        for msg in self._messages:
            if msg.message_id == message_id:
                return {"_id": msg.message_id, "msg": msg.text}
        return None

    async def fetch_messages(
        self,
        room_id: str,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        count: int = 50,
    ) -> list[RoomMessage]:
        messages = self._messages
        if after:
            messages = [m for m in messages if m.timestamp > after]
        if before:
            messages = [m for m in messages if m.timestamp < before]
        return messages[-count:]

    async def list_dm_rooms(self) -> list[dict[str, Any]]:
        return [{"_id": ROOM_ID, "usernames": [USERNAME, self.username]}]

    async def set_status(self, status: str, message: str = "") -> None:
        if status == "away":
            self._console.print(Text("  thinking...", style="dim italic"), end="\r")
        elif log.isEnabledFor(logging.DEBUG):
            log.debug("status: %s %s", status, message)

    async def send_typing(self, room_id: str, typing: bool) -> None:
        pass

    async def react(self, message_id: str, emoji: str) -> None:
        self._console.print(Text(f"  {emoji}", style="dim"))

    async def unreact(self, message_id: str, emoji: str) -> None:
        pass
