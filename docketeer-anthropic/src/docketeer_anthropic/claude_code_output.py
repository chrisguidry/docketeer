"""Output parsing and error handling for claude -p stream-json output."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
)
from docketeer.prompt import ImageBlockParam, MessageParam, TextBlockParam

if TYPE_CHECKING:
    from docketeer.brain.core import ProcessCallbacks

log = logging.getLogger(__name__)


def extract_text(message: MessageParam) -> str:
    """Anthropic Claude Code output parsing utilities."""
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, ImageBlockParam):
            parts.append("[image]")
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, TextBlockParam):
            parts.append(block.text)
    return "\n".join(parts)


def _message_to_content_blocks(msg: MessageParam) -> list[dict]:
    """Convert a MessageParam's content to stream-json content blocks."""
    if isinstance(msg.content, str):
        return [{"type": "text", "text": msg.content}] if msg.content else []
    blocks: list[dict] = []
    for block in msg.content:
        if isinstance(block, (ImageBlockParam, TextBlockParam)):
            blocks.append(block.to_dict())
        elif isinstance(block, str):
            blocks.append({"type": "text", "text": block})
        elif isinstance(block, dict) and block.get("type") == "text":
            blocks.append({"type": "text", "text": block.get("text", "")})
    return blocks


def format_stream_json_input(
    messages: list[MessageParam],
    *,
    resume: bool = False,
) -> str:
    """Build NDJSON input for ``claude -p --input-format stream-json``.

    Images are passed inline as base64 content blocks, so Claude sees them
    natively without needing the Read tool.

    For resumed sessions, only the latest message is sent.  For new sessions,
    the full conversation history is packed into a single user message (with
    assistant turns prefixed ``[assistant]``) so Claude Code gets context.
    """
    if not messages:
        return ""

    if resume or len(messages) <= 1:
        content = _message_to_content_blocks(messages[-1])
    else:
        content: list[dict] = []
        for msg in messages:
            blocks = _message_to_content_blocks(msg)
            if not blocks:
                continue
            if msg.role == "assistant":
                text = extract_text(msg)
                content.append({"type": "text", "text": f"[assistant] {text}"})
            else:
                content.extend(blocks)

    envelope = {
        "type": "user",
        "message": {"role": "user", "content": content},
    }
    return json.dumps(envelope)


def check_process_exit(
    returncode: int | None,
    stderr_bytes: bytes,
) -> None:
    """Log process exit and raise on errors."""
    log.info(
        "claude subprocess exited: code=%s, stderr=%d bytes",
        returncode,
        len(stderr_bytes),
    )

    if stderr_bytes:
        log.info("claude stderr: %s", stderr_bytes.decode(errors="replace").strip())

    if returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace")
        check_error(stderr_text, returncode or 1)


def parse_response(lines: list[str]) -> tuple[str, str | None, dict | None]:
    """Parse stream-json output from claude -p.

    Each ``assistant`` event is a separate turn (possibly separated by tool
    calls).  Text blocks *within* a single turn are concatenated directly;
    text from *different* turns is joined with a blank line so the output
    doesn't smoosh together.

    Returns (text, session_id, result_event).
    """
    turn_texts: list[str] = []
    session_id: str | None = None
    result_event: dict | None = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")

        if etype == "assistant":
            msg = event.get("message", {})
            parts: list[str] = []
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text:  # pragma: no branch
                        parts.append(text)
            if parts:
                turn_texts.append("".join(parts))

        elif etype == "result":  # pragma: no branch
            result_event = event
            session_id = event.get("session_id", session_id)

    return "\n\n".join(turn_texts).strip(), session_id, result_event


async def stream_response(
    stdout: asyncio.StreamReader,
    callbacks: ProcessCallbacks | None = None,
) -> tuple[str, str | None, dict | None]:
    """Read stream-json output line-by-line and fire callbacks as events arrive.

    Returns (final_text, session_id, result_event).  Text from the last turn
    that produced any text is returned, regardless of whether that turn also
    contained tool_use blocks.  Intermediate callback dispatch still suppresses
    narration text that precedes a tool round.
    """
    session_id: str | None = None
    result_event: dict | None = None
    first_text_fired = False
    in_tool_round = False
    stream_events_seen = False
    last_text_only_turn: str = ""
    last_turn_text: str = ""

    while True:
        raw = await stdout.readline()
        if not raw:
            break

        line = raw.decode(errors="replace").strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")

        if etype == "stream_event":
            stream_events_seen = True
            inner = event.get("event", {})
            inner_type = inner.get("type")

            if inner_type == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if not first_text_fired:
                        first_text_fired = True
                        if callbacks and callbacks.on_first_text:
                            await callbacks.on_first_text()
                    if text and callbacks and callbacks.on_text:
                        await callbacks.on_text(text)

            elif inner_type == "content_block_start":
                block = inner.get("content_block", {})
                if block.get("type") == "tool_use":
                    if in_tool_round and callbacks and callbacks.on_tool_end:
                        await callbacks.on_tool_end()
                    if callbacks and callbacks.on_tool_start:
                        await callbacks.on_tool_start(block.get("name", ""))
                    in_tool_round = True
                elif block.get("type") == "text" and in_tool_round:
                    if callbacks and callbacks.on_tool_end:
                        await callbacks.on_tool_end()
                    in_tool_round = False

        elif etype == "assistant":
            msg = event.get("message", {})
            content = msg.get("content", [])

            text_parts: list[str] = []
            has_tool_use = False
            for block in content:
                if block.get("type") == "text":
                    t = block.get("text", "")
                    if t:  # pragma: no branch
                        text_parts.append(t)
                elif block.get("type") == "tool_use":  # pragma: no branch
                    has_tool_use = True

            turn_text = "".join(text_parts) if text_parts else None

            # Dispatch the previous text-only turn as intermediate text,
            # unless this turn is a tool round (that text was narration
            # like "Let me check..." that preceded the tool call).
            if last_text_only_turn:
                if not has_tool_use and callbacks and callbacks.on_text:
                    await callbacks.on_text(last_text_only_turn)
                last_text_only_turn = ""

            if not stream_events_seen and turn_text and not first_text_fired:
                first_text_fired = True
                if callbacks and callbacks.on_first_text:
                    await callbacks.on_first_text()

            if has_tool_use:
                if not stream_events_seen:
                    if in_tool_round and callbacks and callbacks.on_tool_end:
                        await callbacks.on_tool_end()
                    if callbacks and callbacks.on_tool_start:
                        for block in content:
                            if block.get("type") == "tool_use":
                                await callbacks.on_tool_start(block.get("name", ""))
                    in_tool_round = True
            else:
                if (
                    not stream_events_seen
                    and in_tool_round
                    and callbacks
                    and callbacks.on_tool_end
                ):
                    await callbacks.on_tool_end()
                    in_tool_round = False

            if turn_text is not None:
                last_turn_text = turn_text
                if not has_tool_use:
                    last_text_only_turn = turn_text

        elif etype == "result":  # pragma: no branch
            result_event = event
            session_id = event.get("session_id", session_id)

    return last_turn_text, session_id, result_event


def check_error(stderr: str, returncode: int) -> None:
    """Map stderr content to appropriate backend exceptions."""
    lower = stderr.lower()
    if any(re.search(rf"\b{w}\b", lower) for w in ("auth", "unauthorized", "token")):
        raise BackendAuthError(
            f"claude auth error (exit {returncode}): {stderr.strip()}"
        )
    if any(re.search(rf"\b{w}\b", lower) for w in ("context", "too large")):
        raise ContextTooLargeError(
            f"context too large (exit {returncode}): {stderr.strip()}"
        )
    raise BackendError(f"claude error (exit {returncode}): {stderr.strip()}")
