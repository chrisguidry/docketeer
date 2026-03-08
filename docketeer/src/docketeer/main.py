"""Entry point for Docketeer agent - orchestrates Brain and Rocket Chat."""

import argparse
import asyncio
import contextlib
import fcntl
import logging
import sys
from collections.abc import Iterator
from contextlib import AsyncExitStack, contextmanager
from datetime import datetime
from pathlib import Path

from docket import Docket, Worker

from docketeer import environment
from docketeer import logging as docketeer_logging
from docketeer.brain import Brain
from docketeer.chat import (
    ChatClient,
    RoomInfo,
    RoomKind,
    RoomMessage,
    discover_chat_backend,
)
from docketeer.dependencies import (
    set_brain,
    set_client,
    set_docket,
    set_executor,
    set_search,
    set_vault,
)
from docketeer.executor import discover_executor
from docketeer.handlers import process_messages
from docketeer.plugins import discover_all, discover_one
from docketeer.scheduling import register_docket_tools
from docketeer.search import discover_search
from docketeer.tools import ToolContext, registry
from docketeer.vault import discover_vault

log = logging.getLogger(__name__)

DOCKET_URL = environment.get_str("DOCKET_URL", "redis://localhost:6379/0")
DOCKET_NAME = environment.get_str("DOCKET_NAME", "docketeer")


@contextmanager
def _instance_lock(data_dir: Path) -> Iterator[None]:
    """Acquire an exclusive lock file, or exit if another instance is running."""
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / "docketeer.lock"
    lock_file = lock_path.open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        log.warning(
            "Another docketeer instance is already running (lock: %s)", lock_path
        )
        sys.exit(1)
    try:
        yield
    finally:
        lock_file.close()


def _register_task_plugins(docket: Docket) -> None:
    """Discover and register plugin-contributed task collections."""
    for collection in _load_task_collections():
        docket.register_collection(collection)


def _load_task_collections() -> list[str]:
    """Load task collection paths from all docketeer.tasks entry points."""
    collections: list[str] = []
    for plugin_collections in discover_all("docketeer.tasks"):
        collections.extend(plugin_collections)
    return collections


def _format_room_message(
    msg: RoomMessage, previous_timestamp: datetime | None = None
) -> str:
    """Format a single RoomMessage for display."""
    from docketeer.prompt import format_message_time

    ts = format_message_time(msg.timestamp, previous_timestamp)
    thread_tag = f" [thread:{msg.thread_id}]" if msg.thread_id else ""
    lines = [f"[{msg.message_id}] {ts}{thread_tag} @{msg.username}: {msg.text}"]
    if msg.attachments:
        for att in msg.attachments:
            label = att.title or "attachment"
            lines.append(f"  [attachment: {label} ({att.media_type}) — {att.url}]")
    return "\n".join(lines)


def _register_core_chat_tools(client: ChatClient) -> None:
    """Register chat tools that work with any chat provider."""

    @registry.tool(emoji=":speech_balloon:")
    async def list_rooms(ctx: ToolContext) -> str:
        """List all rooms you belong to — channels, groups, and DMs."""
        rooms = _filter_rooms(await client.list_rooms(), client.username)
        if not rooms:
            return "No rooms found."

        lines: list[str] = []
        for room in rooms:
            others = [m for m in room.members if m != client.username]
            match room.kind:
                case RoomKind.direct:
                    label = f"DM with @{others[0]}" if others else "DM"
                case RoomKind.group:
                    label = (
                        f"group DM with @{', @'.join(others)}" if others else "group DM"
                    )
                case RoomKind.private:
                    name = f"#{room.name}" if room.name else "private channel"
                    label = f"{name} (private)"
                case RoomKind.public:
                    label = f"#{room.name}" if room.name else "channel"
                case _:  # pragma: no cover
                    label = room.name or room.room_id
            lines.append(f"  [{room.room_id}] {room.kind.value}: {label}")

        return f"{len(rooms)} room(s):\n" + "\n".join(lines)

    @registry.tool(emoji=":speech_balloon:")
    async def room_messages(
        ctx: ToolContext,
        count: int = 50,
        before: str = "",
        after: str = "",
        room_id: str = "",
    ) -> str:
        """Fetch recent messages from a chat room. Only works on chat lines
        unless you specify a room_id explicitly.

        count: number of messages to retrieve (default 50)
        before: only messages before this ISO 8601 datetime
        after: only messages after this ISO 8601 datetime
        room_id: room to fetch from (defaults to the chat room for this line, if any)
        """
        target_room = room_id or ctx.chat_room
        if not target_room:
            return "No room context available. Specify a room_id to fetch messages."

        before_dt = datetime.fromisoformat(before) if before else None
        after_dt = datetime.fromisoformat(after) if after else None

        messages = await client.fetch_messages(
            target_room,
            before=before_dt,
            after=after_dt,
            count=count,
        )

        if not messages:
            return "No messages found."

        lines: list[str] = []
        previous: datetime | None = None
        for m in messages:
            lines.append(_format_room_message(m, previous))
            previous = m.timestamp
        return "\n".join(lines)

    @registry.tool(emoji=":speech_balloon:")
    async def send_message(
        ctx: ToolContext,
        text: str,
        thread_id: str = "",
        room_id: str = "",
    ) -> str:
        """Send a message to a chat room or thread. Use this to start a thread
        from a message, reply in a specific thread, or post to the channel
        when you're currently in a thread. Only works on chat lines unless
        you specify a room_id explicitly.

        text: the message text
        thread_id: reply in this thread (use a message ID to start a thread from that message)
        room_id: target room (defaults to the chat room for this line, if any)
        """
        target_room = room_id or ctx.chat_room
        await client.send_message(target_room, text, thread_id=thread_id)
        return f"Sent message to {target_room}"

    @registry.tool(emoji=":speech_balloon:")
    async def react(
        ctx: ToolContext,
        message_id: str,
        emoji: str,
        remove: bool = False,
    ) -> str:
        """React to a message with an emoji, or remove a reaction.

        message_id: the ID of the message to react to
        emoji: the emoji name (e.g. :thumbsup: or :tada:)
        remove: set to true to remove the reaction instead of adding it
        """
        if remove:
            await client.unreact(message_id, emoji)
            return f"Removed {emoji} from {message_id}"
        else:
            await client.react(message_id, emoji)
            return f"Added {emoji} to {message_id}"

    @registry.tool
    async def wrap_up_silently(ctx: ToolContext, emoji: str = "") -> str:
        """End your turn without sending a text message. Optionally react to
        the message you're responding to with an emoji.

        emoji: react with this emoji before going silent (e.g. :thumbsup:, :white_check_mark:)
        """
        if emoji and ctx.message_id:
            await client.react(ctx.message_id, emoji)
            return f"Reacted with {emoji} — no message will be sent."
        return "Done — no message will be sent."


async def main() -> None:  # pragma: no cover
    async with AsyncExitStack() as stack:
        stack.enter_context(_instance_lock(environment.DATA_DIR))

        # Ensure data directories exist
        environment.WORKSPACE_PATH.mkdir(parents=True, exist_ok=True)
        environment.AUDIT_PATH.mkdir(parents=True, exist_ok=True)
        environment.USAGE_PATH.mkdir(parents=True, exist_ok=True)
        log.info("Data directory: %s", environment.DATA_DIR.resolve())

        # Discover plugins
        client, register_chat_tools = discover_chat_backend()
        executor = discover_executor()
        vault = discover_vault()

        docket = await stack.enter_async_context(
            Docket(name=DOCKET_NAME, url=DOCKET_URL)
        )
        set_docket(docket)

        search = discover_search(docket=docket)

        # Set tool description template vars based on executor type
        from docketeer.tools.executor import SCRATCH_TARGET, WORKSPACE_TARGET

        if executor.remaps_paths:
            registry.template_vars["workspace"] = str(WORKSPACE_TARGET)
            registry.template_vars["scratch"] = str(SCRATCH_TARGET)
        else:
            workspace = environment.WORKSPACE_PATH
            registry.template_vars["workspace"] = str(workspace)
            registry.template_vars["scratch"] = str(workspace / "tmp")

        # Create tool context
        tool_context = ToolContext(
            workspace=environment.WORKSPACE_PATH,
            executor=executor,
            vault=vault,
            search=search,
        )

        brain = await stack.enter_async_context(Brain(tool_context))

        # Make brain/client/executor/vault available to docket task handlers
        set_brain(brain)
        set_client(client)
        set_executor(executor)
        set_vault(vault)
        set_search(search)
        docket.register_collection("docketeer.tasks:docketeer_tasks")
        _register_task_plugins(docket)

        # Start antenna (realtime event feeds)
        from docketeer.antenna import Antenna
        from docketeer.antenna_tools import register_antenna_tools

        antenna = await stack.enter_async_context(
            Antenna(
                brain.process,
                environment.DATA_DIR,
                environment.WORKSPACE_PATH,
                vault=vault,
            )
        )
        register_antenna_tools(antenna)

        # Register tools (core chat + provider-specific + docket)
        _register_core_chat_tools(client)
        register_chat_tools(client, tool_context)
        register_docket_tools(docket, tool_context)

        worker = await stack.enter_async_context(Worker(docket))
        worker_task = asyncio.create_task(worker.run_forever())

        await stack.enter_async_context(client)
        tool_context.agent_username = client.username
        client._on_message_sent = brain.record_own_message

        log.info("Listening for messages...")
        try:
            await process_messages(client, brain)
        except asyncio.CancelledError:
            pass
        finally:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
            log.info("Disconnected.")


def _filter_rooms(rooms: list[RoomInfo], username: str) -> list[RoomInfo]:
    """Drop self-DMs (DMs with no other members)."""
    return [
        r for r in rooms if not r.kind.is_dm or any(m != username for m in r.members)
    ]


def _will_use_tui() -> bool:
    """Check if the TUI chat backend will be selected, without loading it."""
    try:
        ep = discover_one("docketeer.chat", "CHAT")
    except RuntimeError:
        return False
    return ep is not None and ep.name == "tui"


def run() -> None:
    log_file = None
    if _will_use_tui():
        log_file = environment.DATA_DIR / "docketeer.log"
    docketeer_logging.configure_logging(log_file=log_file)

    parser = argparse.ArgumentParser(description="Docketeer agent")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("start", help="Start the agent")
    run_parser.add_argument(
        "--dev", action="store_true", help="Enable live reload on file changes"
    )

    subparsers.add_parser("snapshot", help="Show what's on the docket")

    args = parser.parse_args()

    if args.command == "snapshot":
        run_snapshot()
    elif args.command == "start":
        if args.dev:
            run_dev()
        else:
            asyncio.run(main())
    else:
        parser.print_help()


def _task_collection_args() -> list[str]:
    """Build --tasks args for the docket CLI, including plugin-contributed tasks."""
    args = ["--tasks", "docketeer.tasks:docketeer_tasks"]
    for collection in _load_task_collections():
        args.extend(["--tasks", collection])
    return args


def run_snapshot() -> None:  # pragma: no cover
    """Exec `docket snapshot` with the right env vars."""
    import os
    import sys

    os.environ["DOCKET_NAME"] = DOCKET_NAME
    os.environ["DOCKET_URL"] = DOCKET_URL
    os.execvp(
        sys.executable,
        [sys.executable, "-m", "docket", "snapshot", *_task_collection_args()],
    )


def run_dev() -> None:  # pragma: no cover
    """Run with live reload on file changes."""
    from watchfiles import run_process

    repo_root = Path(__file__).resolve().parents[3]
    watch_paths = sorted(repo_root.glob("docketeer*/src"))
    log.info("Dev mode: watching %s for changes...", watch_paths)

    run_process(*watch_paths, target=_run_main)


def _run_main() -> None:  # pragma: no cover
    """Target function for watchfiles subprocess."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
