"""Lightweight LLM helpers for webpage summarization and response classification."""

import logging

from anthropic import APIError, AsyncAnthropic
from anthropic.types import MessageParam, TextBlock

log = logging.getLogger(__name__)

COMPACT_MODEL = "claude-haiku-4-5-20251001"


async def summarize_webpage(client: AsyncAnthropic, text: str, purpose: str) -> str:
    """Ask Haiku to summarize a web page, guided by the fetch purpose."""
    focus = f" for someone who wants to: {purpose}" if purpose else ""
    try:
        response = await client.messages.create(
            model=COMPACT_MODEL,
            max_tokens=2048,
            messages=[
                MessageParam(
                    role="user",
                    content=(
                        f"Summarize this web page{focus}. "
                        "Preserve key facts, URLs, numbers, and any structured data. "
                        "Omit navigation, ads, and boilerplate.\n\n"
                        f"{text}"
                    ),
                )
            ],
        )
    except APIError:
        log.warning(
            "Webpage summarization failed, returning truncated text", exc_info=True
        )
        return text[:4000]
    block = response.content[0]
    return block.text if isinstance(block, TextBlock) else str(block)


async def classify_response(
    client: AsyncAnthropic, url: str, status_code: int, headers: str
) -> bool:
    """Ask Haiku whether an HTTP response body is likely readable text."""
    try:
        response = await client.messages.create(
            model=COMPACT_MODEL,
            max_tokens=8,
            messages=[
                MessageParam(
                    role="user",
                    content=(
                        "Given this HTTP response, is the body likely readable text "
                        "(HTML, JSON, plain text, etc.) that would be useful to read? "
                        "Answer only 'true' or 'false'.\n\n"
                        f"URL: {url}\n"
                        f"Status: {status_code}\n"
                        f"Headers:\n{headers}"
                    ),
                )
            ],
        )
    except APIError:
        log.warning("Response classification failed, assuming readable", exc_info=True)
        return True
    block = response.content[0]
    answer = block.text if isinstance(block, TextBlock) else ""
    return answer.strip().lower() == "true"
