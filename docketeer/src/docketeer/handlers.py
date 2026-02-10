"""Message handling: processing loop, content building, response delivery."""

import asyncio
import logging

from anthropic import AuthenticationError, PermissionDeniedError

from docketeer.brain import APOLOGY, Brain, ProcessCallbacks
from docketeer.chat import ChatClient, IncomingMessage, RoomInfo, RoomMessage
from docketeer.prompt import BrainResponse, MessageContent

log = logging.getLogger(__name__)


async def process_messages(client: ChatClient, brain: Brain) -> None:
    """Process incoming messages, interrupting long-running tool loops on new arrivals."""

    async def _on_history(room: RoomInfo, messages: list[RoomMessage]) -> None:
        brain.set_room_info(room.room_id, room)
        brain.load_history(room.room_id, messages)

    msg_iter = client.incoming_messages(on_history=_on_history).__aiter__()
    next_msg = asyncio.create_task(anext(msg_iter, None))

    while True:
        msg = await next_msg
        if msg is None:
            break

        interrupted = asyncio.Event()
        handle_task = asyncio.create_task(
            handle_message(client, brain, msg, interrupted=interrupted)
        )
        next_msg = asyncio.create_task(anext(msg_iter, None))

        done, _ = await asyncio.wait(
            {handle_task, next_msg}, return_when=asyncio.FIRST_COMPLETED
        )

        if handle_task not in done:
            interrupted.set()
            await handle_task

        _check_handle_result(handle_task)


def _check_handle_result(task: asyncio.Task[None]) -> None:
    """Propagate fatal auth errors, log everything else."""
    exc = task.exception()
    if exc is None:
        return
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        raise exc
    log.exception("Unhandled error processing message", exc_info=exc)


async def handle_message(
    client: ChatClient,
    brain: Brain,
    msg: IncomingMessage,
    interrupted: asyncio.Event | None = None,
) -> None:
    """Handle an incoming message."""
    log.info("Message from %s in %s: %s", msg.username, msg.room_id, msg.text[:50])

    # Load history if this is a new room
    if not brain.has_history(msg.room_id):
        log.info("  New room, loading history...")
        history = await client.fetch_messages(msg.room_id)
        count = brain.load_history(msg.room_id, history)
        log.info("    Loaded %d messages", count)

        brain.set_room_info(
            msg.room_id,
            RoomInfo(
                room_id=msg.room_id,
                kind=msg.kind,
                members=[msg.username],
            ),
        )

    content = await build_content(client, msg)

    async def _on_tool_start() -> None:
        await client.send_typing(msg.room_id, False)
        await client.set_status_busy()

    thread_id = msg.thread_id

    callbacks = ProcessCallbacks(
        on_first_text=lambda: client.send_typing(msg.room_id, True),
        on_text=lambda text: client.send_message(
            msg.room_id, text, thread_id=thread_id
        ),
        on_tool_start=_on_tool_start,
        on_tool_end=lambda: client.set_status_available(),
        interrupted=interrupted,
    )

    try:
        response = await brain.process(msg.room_id, content, callbacks=callbacks)
    except (AuthenticationError, PermissionDeniedError):
        raise
    except Exception:
        log.exception(
            "Error processing message from %s in %s", msg.username, msg.room_id
        )
        response = BrainResponse(text=APOLOGY)
    finally:
        await client.send_typing(msg.room_id, False)

    try:
        await send_response(client, msg.room_id, response, thread_id=thread_id)
    except Exception:
        log.exception("Failed to send response to %s", msg.room_id)


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
        message_id=msg.message_id,
        timestamp=timestamp,
        text=msg.text,
        thread_id=msg.thread_id,
        images=images,
    )


async def send_response(
    client: ChatClient, room_id: str, response: BrainResponse, *, thread_id: str = ""
) -> None:
    """Send response to chat (skips empty responses from tool-only turns)."""
    if response.text:
        await client.send_message(room_id, response.text, thread_id=thread_id)
