"""Lightweight LLM helpers for webpage summarization and response classification."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docketeer.brain.backend import InferenceBackend

log = logging.getLogger(__name__)


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
    except Exception:
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
    except Exception:
        log.warning("Response classification failed, assuming readable", exc_info=True)
        return True
    return answer.strip().lower() == "true"
