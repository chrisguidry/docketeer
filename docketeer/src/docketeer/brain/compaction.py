"""History compaction: summarize old messages to free context space."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from docketeer.prompt import MessageParam, extract_text

if TYPE_CHECKING:
    from docketeer.brain.backend import InferenceBackend

log = logging.getLogger(__name__)

MIN_RECENT_MESSAGES = 6


async def compact_history(
    backend: InferenceBackend,
    conversations: dict[str, list[MessageParam]],
    room_id: str,
) -> None:
    """Summarize older messages to free up context space."""
    messages = conversations[room_id]
    if len(messages) <= MIN_RECENT_MESSAGES:
        return

    old_messages = messages[:-MIN_RECENT_MESSAGES]
    recent_messages = messages[-MIN_RECENT_MESSAGES:]

    transcript = "\n".join(
        f"{msg.role if hasattr(msg, 'role') else msg.get('role')}: {text}"
        for msg in old_messages
        if (
            text := extract_text(
                msg.content if hasattr(msg, "content") else msg.get("content")
            )
        )
    )

    if not transcript.strip():
        return

    summary = await summarize_transcript(backend, transcript)
    if summary is None:
        conversations[room_id] = recent_messages
        return

    conversations[room_id] = [
        MessageParam(
            role="user",
            content=f"[Earlier conversation summary]\n{summary}",
        ),
        MessageParam(role="assistant", content="Got it, I have that context."),
        *recent_messages,
    ]


async def summarize_transcript(
    backend: InferenceBackend, transcript: str
) -> str | None:
    """Ask the backend for a conversation summary, or None on failure."""
    try:
        return await backend.utility_complete(
            "Summarize this conversation into a concise recap. "
            "Preserve key facts, decisions, and context that would "
            "be needed to continue the conversation naturally. "
            "Be brief but thorough.\n\n"
            f"{transcript}",
        )
    except Exception:
        log.exception("Summarization failed, falling back to truncation")
        return None
