"""Entry point for Docketeer agent - orchestrates Brain and Rocket Chat."""

import argparse
import asyncio
import contextlib
import fcntl
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from docket import Docket, Worker

from docketeer import environment, tasks
from docketeer.brain import Brain
from docketeer.chat import ChatClient, RoomMessage, discover_chat_backend
from docketeer.dependencies import set_brain, set_client, set_executor
from docketeer.executor import discover_executor
from docketeer.handlers import process_messages
from docketeer.plugins import discover_all
from docketeer.prompt import RoomInfo
from docketeer.tools import ToolContext, registry
from docketeer.vault import discover_vault

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger(__name__)

DOCKET_URL = environment.get_str("DOCKET_URL", "redis://localhost:6379/0")
DOCKET_NAME = environment.get_str("DOCKET_NAME", "docketeer")

_lock_file: Any = None


def _acquire_lock(data_dir: Path) -> None:
    """Acquire an exclusive lock file, or exit if another instance is running."""
    global _lock_file
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / "docketeer.lock"
    # Keep the file open for the lifetime of the process; flock is released on exit.
    _lock_file = lock_path.open("w")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.warning(
            "Another docketeer instance is already running (lock: %s)", lock_path
        )
        sys.exit(1)


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


def _format_room_message(msg: RoomMessage) -> str:
    """Format a single RoomMessage for display."""
    ts = msg.timestamp.astimezone().strftime("%Y-%m-%d %H:%M")
    thread_tag = f" [thread:{msg.thread_id}]" if msg.thread_id else ""
    lines = [f"[{msg.message_id}] {ts}{thread_tag} @{msg.username}: {msg.text}"]
    if msg.attachments:
        for att in msg.attachments:
            label = att.title or "attachment"
            lines.append(f"  [attachment: {label} ({att.media_type}) — {att.url}]")
    return "\n".join(lines)


def _register_core_chat_tools(client: ChatClient) -> None:
    """Register chat tools that work with any chat provider."""

    @registry.tool
    async def room_messages(
        ctx: ToolContext,
        count: int = 50,
        before: str = "",
        after: str = "",
        room_id: str = "",
    ) -> str:
        """Fetch recent messages from a chat room.

        count: number of messages to retrieve (default 50)
        before: only messages before this ISO 8601 datetime
        after: only messages after this ISO 8601 datetime
        room_id: room to fetch from (defaults to the current room)
        """
        target_room = room_id or ctx.room_id

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

        return "\n".join(_format_room_message(m) for m in messages)

    @registry.tool
    async def send_message(
        ctx: ToolContext,
        text: str,
        thread_id: str = "",
        room_id: str = "",
    ) -> str:
        """Send a message to a room or thread. Use this to start a thread
        from a message, reply in a specific thread, or post to the channel
        when you're currently in a thread.

        text: the message text
        thread_id: reply in this thread (use a message ID to start a thread from that message)
        room_id: target room (defaults to current room)
        """
        target_room = room_id or ctx.room_id
        await client.send_message(target_room, text, thread_id=thread_id)
        return f"Sent message to {target_room}"

    @registry.tool
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


def _register_docket_tools(docket: Docket, tool_context: ToolContext) -> None:
    """Register scheduling tools that need the docket instance."""

    @registry.tool
    async def schedule(
        ctx: ToolContext,
        prompt: str,
        when: str,
        key: str = "",
        silent: bool = False,
    ) -> str:
        """Schedule a future task — reminder, follow-up, or background work. The time
        must be in the future — add the delay to the current time shown in your system
        prompt.

        prompt: what to do when the task fires (be specific — future-you needs context)
        when: ISO 8601 datetime in the future (e.g. 2026-02-07T15:00:00-05:00)
        key: unique identifier for cancellation/rescheduling (e.g. "remind-chris-dentist")
        silent: if true, work silently without sending a message (default: false)
        """
        try:
            fire_at = datetime.fromisoformat(when)
        except ValueError:
            return f"Error: invalid datetime format: {when}"

        room_id = "" if silent else ctx.room_id
        thread_id = "" if silent else ctx.thread_id

        if key:
            await docket.replace(tasks.nudge, when=fire_at, key=key)(
                prompt=prompt,
                room_id=room_id,
                thread_id=thread_id,
            )
        else:
            key = f"task-{fire_at.strftime('%Y%m%d-%H%M%S')}"
            await docket.add(tasks.nudge, when=fire_at, key=key)(
                prompt=prompt,
                room_id=room_id,
                thread_id=thread_id,
            )

        local = fire_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")
        mode = "silently" if silent else "in this room"
        return f'Scheduled "{key}" for {local} ({mode})'

    @registry.tool
    async def cancel_task(ctx: ToolContext, key: str) -> str:
        """Cancel a scheduled task.

        key: the task key to cancel
        """
        await docket.cancel(key)
        return f'Cancelled "{key}"'

    @registry.tool
    async def list_scheduled(ctx: ToolContext) -> str:
        """List all scheduled and running tasks."""
        snap = await docket.snapshot()

        lines: list[str] = []

        for ex in snap.future:
            local = ex.when.astimezone().strftime("%Y-%m-%d %H:%M %Z")
            prompt = ex.kwargs.get("prompt", "")
            if len(prompt) > 80:
                prompt = prompt[:77] + "..."
            lines.append(f"  [{ex.key}] {local} — {prompt}")

        for ex in snap.running:
            prompt = ex.kwargs.get("prompt", "")
            if len(prompt) > 80:
                prompt = prompt[:77] + "..."
            lines.append(f"  [{ex.key}] RUNNING — {prompt}")

        if not lines:
            return "No scheduled tasks"
        return f"{len(lines)} task(s):\n" + "\n".join(lines)


async def main() -> None:  # pragma: no cover
    _acquire_lock(environment.DATA_DIR)

    # Ensure data directories exist
    environment.WORKSPACE_PATH.mkdir(parents=True, exist_ok=True)
    environment.AUDIT_PATH.mkdir(parents=True, exist_ok=True)
    log.info("Data directory: %s", environment.DATA_DIR.resolve())

    # Discover plugins
    client, register_chat_tools = discover_chat_backend()
    executor = discover_executor()
    vault = discover_vault()

    # Create tool context
    tool_context = ToolContext(
        workspace=environment.WORKSPACE_PATH, executor=executor, vault=vault
    )

    brain = Brain(tool_context)
    tool_context.on_people_write = brain.rebuild_person_map

    # Make brain/client/executor available to docket task handlers
    set_brain(brain)
    set_client(client)
    if executor:
        set_executor(executor)

    async with Docket(name=DOCKET_NAME, url=DOCKET_URL) as docket:
        docket.register_collection("docketeer.tasks:docketeer_tasks")
        _register_task_plugins(docket)

        # Register tools (core chat + provider-specific + docket)
        _register_core_chat_tools(client)
        register_chat_tools(client, tool_context)
        _register_docket_tools(docket, tool_context)

        async with Worker(docket) as worker:
            worker_task = asyncio.create_task(worker.run_forever())

            await client.connect()
            tool_context.agent_username = client.username

            log.info("Loading conversation history...")
            await load_all_history(client, brain)

            log.info("Subscribing to messages...")
            await client.subscribe_to_my_messages()

            await client.set_status_available()
            log.info("Listening for messages...")
            try:
                await process_messages(client, brain)
            except KeyboardInterrupt:
                pass
            finally:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task
                await client.close()
                log.info("Disconnected.")


async def load_all_history(client: ChatClient, brain: Brain) -> None:
    """Load conversation history for all DM rooms."""
    rooms = await client.list_dm_rooms()
    log.info("Found %d DM rooms", len(rooms))

    for room in rooms:
        room_id = room.get("_id")
        if not room_id:
            continue

        usernames = room.get("usernames", [])
        other_users = [u for u in usernames if u != client.username]
        room_label = ", ".join(other_users) if other_users else room_id

        brain.set_room_info(
            room_id,
            RoomInfo(
                room_id=room_id,
                is_direct=True,
                members=usernames,
            ),
        )

        log.info("  Loading history for DM with %s", room_label)
        history = await client.fetch_messages(room_id)
        count = brain.load_history(room_id, history)
        log.info("    Loaded %d messages", count)


def run() -> None:
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

    os.environ["DOCKET_NAME"] = DOCKET_NAME
    os.environ["DOCKET_URL"] = DOCKET_URL
    os.execvp(
        "docket",
        ["docket", "snapshot", *_task_collection_args()],
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
