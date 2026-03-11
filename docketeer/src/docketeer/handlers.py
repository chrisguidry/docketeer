"""Message handling: processing loop, content building, response delivery."""

import asyncio
import logging

from docketeer.brain import APOLOGY, CHAT_MODEL, Brain, ProcessCallbacks
from docketeer.brain.backend import BackendAuthError
from docketeer.chat import (
    ChatClient,
    IncomingMessage,
    IncomingReaction,
    RoomInfo,
    RoomMessage,
)
from docketeer.prompt import BrainResponse, MessageContent
from docketeer.tools import registry

log = logging.getLogger(__name__)


async def process_messages(client: ChatClient, brain: Brain) -> None:
    """Process incoming messages, interrupting long-running tool loops on new arrivals."""

    async def _on_history(room: RoomInfo, messages: list[RoomMessage]) -> None:
        brain.load_history(line=room.room_id, messages=messages)

    event_iter = client.incoming_messages(on_history=_on_history).__aiter__()
    next_event = asyncio.create_task(anext(event_iter, None))

    while True:
        event = await next_event
        if event is None:
            break

        if isinstance(event, IncomingMessage) and event.is_own:
            await brain.record_own_message(event.room_id, event.text)
            next_event = asyncio.create_task(anext(event_iter, None))
            continue

        interrupted = asyncio.Event()
        if isinstance(event, IncomingReaction):
            handle_task = asyncio.create_task(
                handle_reaction(client, brain, event, interrupted=interrupted)
            )
        else:
            handle_task = asyncio.create_task(
                handle_message(client, brain, event, interrupted=interrupted)
            )
        next_event = asyncio.create_task(anext(event_iter, None))

        done, _ = await asyncio.wait(
            {handle_task, next_event}, return_when=asyncio.FIRST_COMPLETED
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
    if isinstance(exc, BackendAuthError):
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
        count = brain.load_history(line=msg.room_id, messages=history)
        log.info("    Loaded %d messages", count)

    content = await build_content(client, msg)
    room_ctx = await client.room_context(msg.room_id, msg.username)
    slug = await client.room_slug(msg.room_id)

    thread_id = await client.reply_thread_id(msg)
    tool_emojis: set[str] = set()
    stream: object | None = None
    stream_started = False
    stream_failed = False

    async def _on_tool_start(tool_name: str) -> None:
        await client.send_typing(msg.room_id, False)
        emoji = registry.emoji_for(tool_name)
        log.debug("on_tool_start: tool_name=%r, emoji=%r", tool_name, emoji)
        if emoji and emoji not in tool_emojis:
            tool_emojis.add(emoji)
            await client.react(msg.message_id, emoji)

    async def _on_first_text() -> None:
        await client.send_typing(msg.room_id, True)

    async def _on_text(text: str) -> None:
        nonlocal stream, stream_started, stream_failed
        if not text or stream_failed:
            return
        try:
            if stream is None:
                stream = await client.start_reply_stream(msg, thread_id, text)
                if stream is None:
                    stream_failed = True
                    return
                stream_started = True
                return
            await client.append_reply_stream(stream, text)
        except Exception:
            stream_failed = True
            log.exception("Failed to stream response to %s", msg.room_id)

    callbacks = ProcessCallbacks(
        on_first_text=_on_first_text,
        on_text=_on_text,
        on_tool_start=_on_tool_start,
        interrupted=interrupted,
    )

    await client.react(msg.message_id, ":brain:")
    await client.set_thread_status(msg.room_id, thread_id, "is thinking...")
    try:
        response = await brain.process(
            line=msg.room_id,
            content=content,
            callbacks=callbacks,
            tier=CHAT_MODEL,
            room_context=room_ctx,
            room_slug=slug,
            chat_room=msg.room_id,
        )
    except BackendAuthError:
        raise
    except Exception:
        log.exception(
            "Error processing message from %s in %s", msg.username, msg.room_id
        )
        response = BrainResponse(text=APOLOGY)
    finally:
        if stream is not None:
            try:
                await client.stop_reply_stream(stream)
            except Exception:
                log.exception("Failed to finalize reply stream for %s", msg.room_id)
        await client.unreact(msg.message_id, ":brain:")
        await client.set_thread_status(msg.room_id, thread_id, "")
        for emoji in tool_emojis:
            await client.unreact(msg.message_id, emoji)
        await client.send_typing(msg.room_id, False)

    if stream_started and not stream_failed:
        return

    try:
        await send_response(client, msg.room_id, response, thread_id=thread_id)
    except Exception:
        log.exception("Failed to send response to %s", msg.room_id)


async def handle_reaction(
    client: ChatClient,
    brain: Brain,
    reaction: IncomingReaction,
    interrupted: asyncio.Event | None = None,
) -> None:
    """Handle an incoming reaction — lightweight path with no :brain: indicator."""
    log.info(
        "Reaction %s from %s in %s",
        reaction.emoji,
        reaction.username,
        reaction.room_id,
    )

    if not brain.has_history(reaction.room_id):
        log.info("  New room, loading history...")
        history = await client.fetch_messages(reaction.room_id)
        brain.load_history(line=reaction.room_id, messages=history)

    content = MessageContent(
        username=reaction.username,
        message_id=reaction.reacted_msg_id,
        timestamp=reaction.timestamp,
        text=f"reacted with {reaction.emoji}",
    )
    room_ctx = await client.room_context(reaction.room_id, reaction.username)
    slug = await client.room_slug(reaction.room_id)
    callbacks = ProcessCallbacks(interrupted=interrupted)

    try:
        response = await brain.process(
            line=reaction.room_id,
            content=content,
            callbacks=callbacks,
            tier=CHAT_MODEL,
            room_context=room_ctx,
            room_slug=slug,
            chat_room=reaction.room_id,
        )
    except BackendAuthError:
        raise
    except Exception:
        log.exception(
            "Error processing reaction from %s in %s",
            reaction.username,
            reaction.room_id,
        )
        response = BrainResponse(text=APOLOGY)

    try:
        await send_response(client, reaction.room_id, response)
    except Exception:
        log.exception("Failed to send reaction response to %s", reaction.room_id)


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

    return MessageContent(
        username=msg.username,
        message_id=msg.message_id,
        timestamp=msg.timestamp,
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
