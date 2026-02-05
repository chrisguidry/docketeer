"""Entry point for Docketeer agent - orchestrates Brain and Rocket Chat."""

import argparse
import asyncio
import logging
from pathlib import Path

from docketeer.brain import Brain, BrainResponse, HistoryMessage, MessageContent
from docketeer.chat import RocketClient, IncomingMessage
from docketeer.config import Config
from docketeer.tools import ToolExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


async def main() -> None:
    config = Config.from_env()

    # Ensure workspace directory exists
    config.workspace_path.mkdir(parents=True, exist_ok=True)
    log.info("Workspace directory: %s", config.workspace_path.resolve())

    # Create tool executor
    tool_executor = ToolExecutor(config.workspace_path)

    client = RocketClient(
        config.rocketchat_url, config.rocketchat_username, config.rocketchat_password
    )
    brain = Brain(config, tool_executor)

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

    # Show typing indicator
    await client.send_typing(msg.room_id)

    # Build content for Brain (fetch any images)
    content = build_content(client, msg)

    # Get response from Brain
    response = await brain.process(msg.room_id, content)

    # Send response with tool call attachments
    send_response(client, msg.room_id, response)


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
    """Send response to Rocket Chat, with tool calls as attachments."""
    attachments = []

    for tool_call in response.tool_calls:
        # Format args nicely
        args_str = ", ".join(f"{k}={v!r}" for k, v in tool_call.args.items())

        # Truncate long results
        result_preview = tool_call.result
        if len(result_preview) > 200:
            result_preview = result_preview[:200] + "..."

        attachments.append({
            "color": "#dc3545" if tool_call.is_error else "#28a745",
            "title": f"🔧 {tool_call.name}({args_str})",
            "text": result_preview,
            "collapsed": True,
        })

    if attachments:
        client.send_message(room_id, response.text, attachments=attachments)
    else:
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
