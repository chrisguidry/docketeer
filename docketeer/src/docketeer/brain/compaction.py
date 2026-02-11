"""History compaction: summarize old messages to free context space."""

import logging

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlock

from docketeer.prompt import extract_text

log = logging.getLogger(__name__)

MIN_RECENT_MESSAGES = 6


def _haiku_model_id() -> str:
    from docketeer.brain.core import MODELS

    return MODELS["haiku"].model_id


async def compact_history(
    client: AsyncAnthropic,
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
        f"{msg['role']}: {text}"
        for msg in old_messages
        if (text := extract_text(msg["content"]))
    )

    if not transcript.strip():
        return

    summary = await summarize_transcript(client, transcript)
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


async def summarize_transcript(client: AsyncAnthropic, transcript: str) -> str | None:
    """Ask Haiku for a conversation summary, or None on failure."""
    try:
        summary_response = await client.messages.create(
            model=_haiku_model_id(),
            max_tokens=1024,
            messages=[
                MessageParam(
                    role="user",
                    content=(
                        "Summarize this conversation into a concise recap. "
                        "Preserve key facts, decisions, and context that would "
                        "be needed to continue the conversation naturally. "
                        "Be brief but thorough.\n\n"
                        f"{transcript}"
                    ),
                )
            ],
        )
        block = summary_response.content[0]
        return block.text if isinstance(block, TextBlock) else str(block)
    except Exception:
        log.exception("Summarization failed, falling back to truncation")
        return None
