"""Terminal chat client for local development."""

import logging
import secrets
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from docketeer.chat import ChatClient, IncomingMessage, RoomMessage

log = logging.getLogger(__name__)

ROOM_ID = "terminal"
USER_ID = "local-user"
USERNAME = "you"

INPUT_PROMPT = "you > "


def _redirect_logs_to_file(data_dir: Path) -> Path:
    """Redirect all logging to a file so the TUI stays clean."""
    log_path = data_dir / "docketeer.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(file_handler)
    return log_path


@contextmanager
def _patched_stdout() -> Generator[None]:
    """Wrap patch_stdout so tests can easily mock it out."""
    with patch_stdout():
        yield


class TUIClient(ChatClient):
    """Chat client that reads from stdin and writes to the terminal.

    Uses prompt_toolkit to maintain a fixed input area at the bottom of the
    terminal while agent responses scroll above it.
    """

    username = "docketeer"
    user_id = "docketeer-tui"

    def __init__(self) -> None:
        self._console = Console()
        self._session: PromptSession[str] | None = None
        self._messages: list[RoomMessage] = []
        self._closed = False
        self._stdout_ctx: Any = None

    async def connect(self) -> None:
        from docketeer import environment

        log_path = _redirect_logs_to_file(environment.DATA_DIR)

        history_file = environment.DATA_DIR / ".tui-history.txt"
        self._session = PromptSession(history=FileHistory(str(history_file)))

        # patch_stdout makes all print() / Console.print() output render
        # above the prompt_toolkit input line — the key to two-region UX
        self._stdout_ctx = _patched_stdout()
        self._stdout_ctx.__enter__()

        # recreate Console AFTER patch_stdout so it writes through the proxy;
        # force_terminal=True because the proxy doesn't report as a TTY
        self._console = Console(force_terminal=True)

        self._console.print()
        self._console.rule("[bold]docketeer[/bold]")
        self._console.print("  type a message and press enter. ctrl-c to quit.")
        self._console.print(f"  logs: {log_path}")
        self._console.print()

    async def close(self) -> None:
        self._closed = True
        self._console.print()
        self._console.rule("[dim]disconnected[/dim]")
        if self._stdout_ctx:
            self._stdout_ctx.__exit__(None, None, None)
            self._stdout_ctx = None

    async def subscribe_to_my_messages(self) -> None:
        pass

    async def incoming_messages(self) -> AsyncGenerator[IncomingMessage, None]:
        while not self._closed:
            try:
                text = await self._read_input()
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

    async def _read_input(self) -> str | None:
        """Read a line from the user via prompt_toolkit."""
        assert self._session is not None
        try:
            return await self._session.prompt_async(INPUT_PROMPT)
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
        panel = Panel(
            Markdown(text),
            title="[bold]docketeer[/bold]",
            title_align="left",
            border_style="blue",
            box=box.ROUNDED,
            padding=(0, 1),
        )
        self._console.print(panel)

    async def upload_file(
        self, room_id: str, file_path: str, message: str = "", *, thread_id: str = ""
    ) -> None:
        parts: list[str] = []
        if message:
            parts.append(message)
        parts.append(f"[file: {file_path}]")
        panel = Panel(
            "\n".join(parts),
            title="[bold]docketeer[/bold]",
            title_align="left",
            border_style="blue",
            box=box.ROUNDED,
            padding=(0, 1),
        )
        self._console.print(panel)

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
            self._console.print(Text("  thinking...", style="dim italic"))
        elif log.isEnabledFor(logging.DEBUG):
            log.debug("status: %s %s", status, message)

    async def send_typing(self, room_id: str, typing: bool) -> None:
        pass

    async def react(self, message_id: str, emoji: str) -> None:
        self._console.print(Text(f"  {emoji}", style="dim"))

    async def unreact(self, message_id: str, emoji: str) -> None:
        pass
