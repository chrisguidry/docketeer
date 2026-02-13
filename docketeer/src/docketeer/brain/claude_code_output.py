"""Output parsing and error handling for claude -p stream-json output."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
)

if TYPE_CHECKING:
    from docketeer.brain.core import ProcessCallbacks

log = logging.getLogger(__name__)


def extract_text(message: dict) -> str:
    """Pull text from a message's content (string or list-of-blocks)."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def format_prompt(messages: list[dict], *, resume: bool = False) -> str:
    """Build the prompt to send to claude -p.

    For resumed sessions, only the latest message is needed since Claude Code
    has the prior context internally.  For new sessions, include the full
    conversation history so Claude Code can see what was said before it joined.
    """
    if not messages:
        return ""

    if resume or len(messages) <= 1:
        return extract_text(messages[-1])

    parts: list[str] = []
    for msg in messages:
        text = extract_text(msg)
        if not text:
            continue
        if msg.get("role") == "assistant":
            parts.append(f"[assistant] {text}")
        else:
            parts.append(text)

    return "\n".join(parts)


def check_process_exit(
    proc: asyncio.subprocess.Process,
    stderr_bytes: bytes,
) -> None:
    """Log process exit and raise on errors."""
    log.info(
        "claude subprocess exited: code=%s, stderr=%d bytes",
        proc.returncode,
        len(stderr_bytes),
    )

    if stderr_bytes:
        log.info("claude stderr: %s", stderr_bytes.decode(errors="replace").strip())

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace")
        check_error(stderr_text, proc.returncode or 1)


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

    Returns (final_text, session_id, result_event).  Intermediate text (from
    turns that also contain tool_use blocks) is dispatched via
    ``callbacks.on_text`` as it streams; only the final text-only turn is
    returned to the caller.
    """
    session_id: str | None = None
    result_event: dict | None = None
    first_text_fired = False
    in_tool_round = False
    stream_events_seen = False
    pending_final: str | None = None

    while True:
        raw = await stdout.readline()
        if not raw:
            break

        line = raw.decode(errors="replace").strip()
        if not line:
            continue

        log.debug("stream-json raw: %s", line)

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
                if delta.get("type") == "text_delta" and not first_text_fired:
                    first_text_fired = True
                    if callbacks and callbacks.on_first_text:
                        await callbacks.on_first_text()

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

            # If we had a buffered text-only turn and now see another assistant
            # event, the buffered one was intermediate — dispatch it.
            if pending_final is not None:
                if callbacks and callbacks.on_text:
                    await callbacks.on_text(pending_final)
                pending_final = None

            if not stream_events_seen and turn_text and not first_text_fired:
                first_text_fired = True
                if callbacks and callbacks.on_first_text:
                    await callbacks.on_first_text()

            if has_tool_use:
                if turn_text and callbacks and callbacks.on_text:
                    await callbacks.on_text(turn_text)
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
                if turn_text is not None:  # pragma: no branch
                    pending_final = turn_text

        elif etype == "result":  # pragma: no branch
            result_event = event
            session_id = event.get("session_id", session_id)

    return pending_final or "", session_id, result_event


def check_error(stderr: str, returncode: int) -> None:
    """Map stderr content to appropriate backend exceptions."""
    lower = stderr.lower()
    if any(word in lower for word in ("auth", "unauthorized", "token")):
        raise BackendAuthError(
            f"claude auth error (exit {returncode}): {stderr.strip()}"
        )
    if any(word in lower for word in ("context", "too large")):
        raise ContextTooLargeError(
            f"context too large (exit {returncode}): {stderr.strip()}"
        )
    raise BackendError(f"claude error (exit {returncode}): {stderr.strip()}")
