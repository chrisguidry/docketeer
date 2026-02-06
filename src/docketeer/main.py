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

from docketeer import tasks
from docketeer.brain import Brain, BrainResponse, HistoryMessage, MessageContent
from docketeer.chat import IncomingMessage, RocketClient, _parse_rc_timestamp
from docketeer.config import Config
from docketeer.tools import ToolContext, _safe_path, registry

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger(__name__)

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


def _register_chat_tools(client: RocketClient, tool_context: ToolContext) -> None:
    """Register tools that need the chat client."""

    @registry.tool
    async def send_file(ctx: ToolContext, path: str, message: str = "") -> str:
        """Send a file from the workspace to the current chat room.

        path: relative path to the file in workspace
        message: optional message to include with the file
        """
        target = _safe_path(ctx.workspace, path)
        if not target.exists():
            return f"File not found: {path}"
        if target.is_dir():
            return f"Cannot send a directory: {path}"

        await client.upload_file(ctx.room_id, str(target), message=message)
        return f"Sent {path} to chat"


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
        """Schedule a future task — reminder, follow-up, or background work. The time must be in the future — add the delay to the current time shown in your system prompt.

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


async def main() -> None:
    config = Config.from_env()
    _acquire_lock(config.data_dir)

    # Ensure data directories exist
    config.workspace_path.mkdir(parents=True, exist_ok=True)
    config.audit_path.mkdir(parents=True, exist_ok=True)
    log.info("Data directory: %s", config.data_dir.resolve())

    # Create tool context
    tool_context = ToolContext(workspace=config.workspace_path, config=config)

    client = RocketClient(
        config.rocketchat_url, config.rocketchat_username, config.rocketchat_password
    )
    brain = Brain(config, tool_context)
    tool_context.on_people_write = brain.rebuild_person_map

    # Make brain/client available to docket task handlers
    tasks.set_brain(brain)
    tasks.set_client(client)

    async with Docket(name=config.docket_name, url=config.docket_url) as docket:
        docket.register_collection("docketeer.tasks:docketeer_tasks")

        # Register tools (chat + docket)
        _register_chat_tools(client, tool_context)
        _register_docket_tools(docket, tool_context)

        async with Worker(docket) as worker:
            worker_task = asyncio.create_task(worker.run_forever())

            log.info("Connecting to Rocket Chat at %s...", config.rocketchat_url)
            await client.connect()

            log.info("Loading conversation history...")
            await load_all_history(client, brain)

            log.info("Subscribing to messages...")
            await client.subscribe_to_my_messages()

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


async def load_all_history(client: RocketClient, brain: Brain) -> None:
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

        log.info("  Loading history for DM with %s", room_label)
        history = await fetch_history_for_brain(client, room_id)
        count = brain.load_history(room_id, history)
        log.info("    Loaded %d messages", count)


def _format_timestamp(ts: Any) -> str:
    """Parse an RC timestamp and format it in local time."""
    dt = _parse_rc_timestamp(ts)
    if not dt:
        return ""
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


async def fetch_history_for_brain(
    client: RocketClient, room_id: str
) -> list[HistoryMessage]:
    """Fetch room history and convert to Brain's format."""
    raw_history = await client.fetch_room_history(room_id, count=20)
    messages = []

    for msg in raw_history:
        if msg.get("t"):
            continue

        text = msg.get("msg", "")
        if not text:
            continue

        user = msg.get("u", {})
        username = user.get("username", "unknown")
        is_bot = user.get("_id") == client._user_id
        role = "assistant" if is_bot else "user"
        timestamp = _format_timestamp(msg.get("ts"))

        messages.append(
            HistoryMessage(
                role=role,
                username=username,
                text=text,
                timestamp=timestamp,
            )
        )

    return messages


async def handle_message(
    client: RocketClient, brain: Brain, msg: IncomingMessage
) -> None:
    """Handle an incoming message."""
    log.info("Message from %s in %s: %s", msg.username, msg.room_id, msg.text[:50])

    # Load history if this is a new room
    if not brain.has_history(msg.room_id):
        log.info("  New room, loading history...")
        history = await fetch_history_for_brain(client, msg.room_id)
        count = brain.load_history(msg.room_id, history)
        log.info("    Loaded %d messages", count)

    await client.set_status("away")
    try:
        content = await build_content(client, msg)
        response = await brain.process(msg.room_id, content)
        await send_response(client, msg.room_id, response)
    finally:
        await client.set_status("online")


async def build_content(client: RocketClient, msg: IncomingMessage) -> MessageContent:
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
    client: RocketClient, room_id: str, response: BrainResponse
) -> None:
    """Send response to Rocket Chat."""
    await client.send_message(room_id, response.text)


def run() -> None:
    parser = argparse.ArgumentParser(description="Docketeer agent")
    parser.add_argument(
        "--dev", action="store_true", help="Enable live reload on file changes"
    )
    args = parser.parse_args()

    if args.dev:
        run_dev()
    else:
        asyncio.run(main())


def run_dev() -> None:
    """Run with live reload on file changes."""
    from watchfiles import run_process

    src_path = Path(__file__).parent
    log.info("Dev mode: watching %s for changes...", src_path)

    run_process(src_path, target=_run_main)


def _run_main() -> None:
    """Target function for watchfiles subprocess."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
