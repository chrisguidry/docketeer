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
from docketeer.brain import Brain, ProcessCallbacks
from docketeer.chat import ChatClient, IncomingMessage
from docketeer.dependencies import set_brain, set_client
from docketeer.prompt import BrainResponse, MessageContent, RoomInfo
from docketeer.tools import ToolContext, registry

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


def _discover_chat_backend() -> tuple[ChatClient, Any]:
    """Discover the chat backend via entry_points."""
    from importlib.metadata import entry_points

    eps = list(entry_points(group="docketeer.chat"))
    if not eps:
        raise RuntimeError("No chat backend installed")
    module = eps[0].load()
    client = module.create_client()
    register_fn = getattr(module, "register_tools", None)
    return client, register_fn


def _register_task_plugins(docket: Docket) -> None:
    """Discover and register plugin-contributed task collections."""
    for collection in _load_task_collections():
        docket.register_collection(collection)


def _load_task_collections() -> list[str]:
    """Load task collection paths from all docketeer.tasks entry points."""
    from importlib.metadata import entry_points

    collections: list[str] = []
    for ep in entry_points(group="docketeer.tasks"):
        try:
            collections.extend(ep.load())
        except Exception:
            log.warning("Failed to load task plugin: %s", ep.name, exc_info=True)
    return collections


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

        if key:
            await docket.replace(tasks.nudge, when=fire_at, key=key)(
                prompt=prompt,
                room_id=room_id,
            )
        else:
            key = f"task-{fire_at.strftime('%Y%m%d-%H%M%S')}"
            await docket.add(tasks.nudge, when=fire_at, key=key)(
                prompt=prompt,
                room_id=room_id,
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

    # Create tool context
    tool_context = ToolContext(workspace=environment.WORKSPACE_PATH)

    client, register_chat_tools = _discover_chat_backend()
    brain = Brain(tool_context)
    tool_context.on_people_write = brain.rebuild_person_map

    # Make brain/client available to docket task handlers
    set_brain(brain)
    set_client(client)

    async with Docket(name=DOCKET_NAME, url=DOCKET_URL) as docket:
        docket.register_collection("docketeer.tasks:docketeer_tasks")
        _register_task_plugins(docket)

        # Register tools (chat + docket)
        if register_chat_tools:
            register_chat_tools(client, tool_context)
        _register_docket_tools(docket, tool_context)

        async with Worker(docket) as worker:
            worker_task = asyncio.create_task(worker.run_forever())

            await client.connect()

            log.info("Loading conversation history...")
            await load_all_history(client, brain)

            log.info("Subscribing to messages...")
            await client.subscribe_to_my_messages()

            await client.set_status_available()
            log.info("Listening for messages...")
            try:
                async for msg in client.incoming_messages():
                    await handle_message(client, brain, msg)
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
        history = await client.fetch_history_as_messages(room_id)
        count = brain.load_history(room_id, history)
        log.info("    Loaded %d messages", count)


async def handle_message(
    client: ChatClient, brain: Brain, msg: IncomingMessage
) -> None:
    """Handle an incoming message."""
    log.info("Message from %s in %s: %s", msg.username, msg.room_id, msg.text[:50])

    # Load history if this is a new room
    if not brain.has_history(msg.room_id):
        log.info("  New room, loading history...")
        history = await client.fetch_history_as_messages(msg.room_id)
        count = brain.load_history(msg.room_id, history)
        log.info("    Loaded %d messages", count)

        brain.set_room_info(
            msg.room_id,
            RoomInfo(
                room_id=msg.room_id,
                is_direct=msg.is_direct,
                members=[msg.username],
            ),
        )

    content = await build_content(client, msg)

    async def _on_tool_start() -> None:
        await client.send_typing(msg.room_id, False)
        await client.set_status_busy()

    callbacks = ProcessCallbacks(
        on_first_text=lambda: client.send_typing(msg.room_id, True),
        on_tool_start=_on_tool_start,
        on_tool_end=lambda: client.set_status_available(),
    )

    try:
        response = await brain.process(msg.room_id, content, callbacks=callbacks)
    finally:
        await client.send_typing(msg.room_id, False)
    await send_response(client, msg.room_id, response)


async def build_content(client: ChatClient, msg: IncomingMessage) -> MessageContent:
    """Build MessageContent from an IncomingMessage, fetching any attachments."""
    images = []

    if msg.attachments:
        for att in msg.attachments:
            try:
                data = await client.fetch_attachment(att.url)
                images.append((att.media_type, data))
            except Exception as e:
                log.warning("Failed to fetch attachment %s: %s", att.url, e)

    timestamp = ""
    if msg.timestamp:
        timestamp = msg.timestamp.astimezone().strftime("%Y-%m-%d %H:%M")

    return MessageContent(
        username=msg.username,
        timestamp=timestamp,
        text=msg.text,
        images=images,
    )


async def send_response(
    client: ChatClient, room_id: str, response: BrainResponse
) -> None:
    """Send response to Rocket Chat (skips empty responses from tool-only turns)."""
    if response.text:
        await client.send_message(room_id, response.text)


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
