"""Shared helpers for the brain: LLM utilities and message formatting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from docketeer.brain.backend import BackendError
from docketeer.prompt import MessageParam

if TYPE_CHECKING:
    from docketeer.brain.backend import InferenceBackend

log = logging.getLogger(__name__)

MAX_LOG_CONTENT_LENGTH = 500


def format_message_content(content: str | list) -> str:
    """Extract and truncate message content for logging."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        text = "\n".join(parts)
    else:
        text = str(content)

    if len(text) > MAX_LOG_CONTENT_LENGTH:
        return text[:MAX_LOG_CONTENT_LENGTH] + "..."
    return text


def format_message_for_log(msg: MessageParam) -> str:
    """Format a message for logging (no system prompts)."""
    content = format_message_content(msg.content)
    tool_calls = msg.tool_calls

    if tool_calls:
        tc_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
        return f"tools={tc_names}: {content[:200]}"

    # For user messages, extract just the actual text (strip @username: prefix)
    if msg.role == "user" and ": " in content:
        content = content.split(": ", 1)[1]

    return content


async def summarize_webpage(backend: InferenceBackend, text: str, purpose: str) -> str:
    """Ask the backend to summarize a web page, guided by the fetch purpose."""
    focus = f" for someone who wants to: {purpose}" if purpose else ""
    try:
        return await backend.utility_complete(
            f"Summarize this web page{focus}. "
            "Preserve key facts, URLs, numbers, and any structured data. "
            "Omit navigation, ads, and boilerplate.\n\n"
            f"{text}",
            max_tokens=2048,
        )
    except BackendError:
        log.warning(
            "Webpage summarization failed, returning truncated text", exc_info=True
        )
        return text[:4000]


async def classify_response(
    backend: InferenceBackend, url: str, status_code: int, headers: str
) -> bool:
    """Ask the backend whether an HTTP response body is likely readable text."""
    try:
        answer = await backend.utility_complete(
            "Given this HTTP response, is the body likely readable text "
            "(HTML, JSON, plain text, etc.) that would be useful to read? "
            "Answer only 'true' or 'false'.\n\n"
            f"URL: {url}\n"
            f"Status: {status_code}\n"
            f"Headers:\n{headers}",
            max_tokens=8,
        )
    except BackendError:
        log.warning("Response classification failed, assuming readable", exc_info=True)
        return True
    return answer.strip().lower() == "true"
