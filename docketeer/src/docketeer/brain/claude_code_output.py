"""Output parsing and error handling for claude -p stream-json output."""

from __future__ import annotations

import asyncio
import json
import logging

from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
)

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


def handle_claude_output(
    proc: asyncio.subprocess.Process,
    stdout_bytes: bytes,
    stderr_bytes: bytes,
) -> tuple[str, str | None]:
    """Parse claude output and raise on errors."""
    log.info(
        "claude subprocess exited: code=%s, stdout=%d bytes, stderr=%d bytes",
        proc.returncode,
        len(stdout_bytes),
        len(stderr_bytes),
    )

    if stderr_bytes:
        log.info("claude stderr: %s", stderr_bytes.decode(errors="replace").strip())

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace")
        check_error(stderr_text, proc.returncode or 1)

    stdout_text = stdout_bytes.decode(errors="replace")
    lines = stdout_text.splitlines()
    log.info("Parsing %d lines of stream-json output", len(lines))
    return parse_response(lines)


def parse_response(lines: list[str]) -> tuple[str, str | None]:
    """Parse stream-json output from claude -p.

    Each ``assistant`` event is a separate turn (possibly separated by tool
    calls).  Text blocks *within* a single turn are concatenated directly;
    text from *different* turns is joined with a blank line so the output
    doesn't smoosh together.
    """
    turn_texts: list[str] = []
    session_id: str | None = None

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
            session_id = event.get("session_id", session_id)

    return "\n\n".join(turn_texts).strip(), session_id


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
