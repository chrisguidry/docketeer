"""Entry point for Docketeer agent - orchestrates Brain and Rocket Chat."""

import argparse
import asyncio
import fcntl
import logging
import sys
from pathlib import Path

from docketeer.brain import Brain, BrainResponse, HistoryMessage, MessageContent
from docketeer.chat import RocketClient, IncomingMessage
from docketeer.config import Config
from docketeer.tools import ToolContext, _safe_path, registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


def _acquire_lock(data_dir: Path) -> None:
    """Acquire an exclusive lock file, or exit if another instance is running."""
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / "docketeer.lock"
    # Keep the file open for the lifetime of the process; flock is released on exit.
    lock_file = lock_path.open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("Another docketeer instance is already running (lock: %s)", lock_path)
        sys.exit(1)
    # Stash on the module so the GC doesn't close it.
    _acquire_lock._lock_file = lock_file


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

        client.upload_file(ctx.room_id, str(target), message=message)
        return f"Sent {path} to chat"


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

    # Register chat-specific tools
    _register_chat_tools(client, tool_context)

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
        await client.close()
        log.info("Disconnected.")


async def load_all_history(client: RocketClient, brain: Brain) -> None:
    """Load conversation history for all DM rooms."""
    rooms = client.list_dm_rooms()
    log.info("Found %d DM rooms", len(rooms))

    for room in rooms:
        room_id = room.get("_id")
        if not room_id:
            continue

        usernames = room.get("usernames", [])
        other_users = [u for u in usernames if u != client.username]
        room_label = ", ".join(other_users) if other_users else room_id

        log.info("  Loading history for DM with %s", room_label)
        history = fetch_history_for_brain(client, room_id)
        count = brain.load_history(room_id, history)
        log.info("    Loaded %d messages", count)


def fetch_history_for_brain(client: RocketClient, room_id: str) -> list[HistoryMessage]:
    """Fetch room history and convert to Brain's format."""
    raw_history = client.fetch_room_history(room_id, count=20)
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

        messages.append(HistoryMessage(role=role, username=username, text=text))

    return messages


async def handle_message(client: RocketClient, brain: Brain, msg: IncomingMessage) -> None:
    """Handle an incoming message."""
    log.info("Message from %s in %s: %s", msg.username, msg.room_id, msg.text[:50])

    # Load history if this is a new room
    if not brain.has_history(msg.room_id):
        log.info("  New room, loading history...")
        history = fetch_history_for_brain(client, msg.room_id)
        count = brain.load_history(msg.room_id, history)
        log.info("    Loaded %d messages", count)

    client.set_status("away")
    try:
        content = build_content(client, msg)
        response = await brain.process(msg.room_id, content)
        send_response(client, msg.room_id, response)
    finally:
        client.set_status("online")


def build_content(client: RocketClient, msg: IncomingMessage) -> MessageContent:
    """Build MessageContent from an IncomingMessage, fetching any attachments."""
    images = []

    if msg.attachments:
        for att in msg.attachments:
            try:
                data = client.fetch_attachment(att.url)
                images.append((att.media_type, data))
            except Exception as e:
                log.warning("Failed to fetch attachment %s: %s", att.url, e)

    return MessageContent(username=msg.username, text=msg.text, images=images)


def send_response(client: RocketClient, room_id: str, response: BrainResponse) -> None:
    """Send response to Rocket Chat."""
    client.send_message(room_id, response.text)


def run() -> None:
    parser = argparse.ArgumentParser(description="Docketeer agent")
    parser.add_argument("--dev", action="store_true", help="Enable live reload on file changes")
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
