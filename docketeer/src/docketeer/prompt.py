"""System prompt construction and shared message types."""

import importlib.resources
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from docketeer.people import load_person_context
from docketeer.plugins import discover_all

log = logging.getLogger(__name__)


@dataclass
class CacheControl:
    """Prompt caching control."""

    ttl: Literal["5m", "1h"] = "5m"

    def to_dict(self) -> dict[str, str]:
        return {"type": "ephemeral", "ttl": self.ttl}


@dataclass
class SystemBlock:
    """A text block in the system prompt."""

    text: str
    cache_control: CacheControl | None = None

    def to_dict(self) -> dict[str, str | dict]:
        """Serialize to a dictionary representation."""
        d = {"type": "text", "text": self.text}
        if self.cache_control:
            d["cache_control"] = self.cache_control.to_dict()
        return d


def _load_prompt_providers() -> list[Callable[[Path], list[SystemBlock]]]:
    return discover_all("docketeer.prompt")


_prompt_providers = _load_prompt_providers()


@dataclass
class MessageContent:
    """Content to send to Claude - text and/or images."""

    username: str
    message_id: str = ""
    timestamp: datetime | None = None
    text: str = ""
    thread_id: str = ""
    images: list[tuple[str, bytes]] = field(default_factory=list)


def format_message_time(timestamp: datetime, previous: datetime | None = None) -> str:
    """Format a message timestamp as absolute time or delta from previous.

    No previous → absolute: 2026-02-06 10:00
    With previous → delta: +30s, +5m, +2h 15m, +1d 3h
    Two units max, trailing zero components dropped, negative deltas clamped to +0s.
    """
    if previous is None:
        return timestamp.astimezone().strftime("%Y-%m-%d %H:%M")

    total_seconds = int((timestamp - previous).total_seconds())
    if total_seconds < 0:
        total_seconds = 0

    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return "+" + " ".join(parts[:2])


@dataclass
class BrainResponse:
    """Response from Brain."""

    text: str


def ensure_template(workspace: Path, filename: str) -> None:
    """Copy a template from the package to the workspace if it doesn't exist."""
    stem, ext = filename.rsplit(".", 1)
    target = workspace / f"{stem.upper()}.{ext}"
    if target.exists():
        return
    source = importlib.resources.files("docketeer").joinpath(filename)
    target.write_text(source.read_text())
    log.info("Copied %s template to %s", filename, target)


def build_system_blocks(workspace: Path) -> list[SystemBlock]:
    """Build system prompt as stable content blocks for prompt caching.

    All content here is static between requests so that tools + system form
    a fully cacheable prefix. Dynamic per-request context (time, room, person)
    goes into the user message via build_dynamic_context().
    """
    soul_path = workspace / "SOUL.md"
    stable_text = soul_path.read_text()

    practice_path = workspace / "PRACTICE.md"
    if practice_path.exists():
        stable_text += "\n\n" + practice_path.read_text()

    bootstrap_path = workspace / "BOOTSTRAP.md"
    if bootstrap_path.exists():
        stable_text += "\n\n" + bootstrap_path.read_text()

    blocks: list[SystemBlock] = [
        SystemBlock(text=stable_text),
    ]

    for provider in _prompt_providers:
        try:
            blocks.extend(provider(workspace))
        except Exception:
            log.warning("Prompt provider %s failed", provider, exc_info=True)

    blocks[-1].cache_control = CacheControl()

    return blocks


def build_dynamic_context(
    current_time: str,
    username: str,
    workspace: Path,
    room_context: str = "",
) -> str:
    """Build per-request dynamic context to prepend to the user message.

    Kept out of the system prompt so that tools + system form a stable
    cacheable prefix.
    """
    parts = [f"Current time: {current_time}"]

    if room_context:
        parts.append(room_context)

    parts.append(f"Talking to: @{username}")

    person_context = load_person_context(workspace, username)
    if person_context:
        parts.append(f"\n## What I know about @{username}\n\n{person_context}")
    else:
        parts.append(
            f"\nI don't have a profile for @{username} yet. "
            f"I can create people/{username}/profile.md to start one, "
            f"or if I know this person under another name, "
            f"I can create a symlink with the create_link tool."
        )

    return "\n".join(parts)


def extract_text(content: str | Iterable) -> str:
    """Pull plain text from message content, skipping images and tool results."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block["text"])
            elif block.get("type") == "tool_result":
                result = block.get("content", "")
                if isinstance(result, str) and result:
                    parts.append(f"[tool result: {result[:200]}]")
        elif hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)


@dataclass
class TextBlockParam:
    """A text block."""

    text: str
    type: Literal["text"] = "text"

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "text": self.text}


@dataclass
class Base64ImageSourceParam:
    """Base64 encoded image source."""

    media_type: str
    data: str
    type: Literal["base64"] = "base64"

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "media_type": self.media_type, "data": self.data}


@dataclass
class ImageBlockParam:
    """An image block."""

    source: Base64ImageSourceParam
    type: Literal["image"] = "image"

    def to_dict(self) -> dict[str, str | dict[str, str]]:
        return {"type": self.type, "source": self.source.to_dict()}


ContentBlockParam = TextBlockParam | ImageBlockParam


@dataclass
class MessageParam:
    """A message parameter for Chat API."""

    role: Literal["user", "assistant", "system"]
    content: str | list[Any]

    def to_dict(self) -> dict:
        """Convert to a dictionary for API usage."""
        if isinstance(self.content, str):
            return {"role": self.role, "content": self.content}
        elif isinstance(self.content, list):
            serialized_content = []
            for block in self.content:
                if callable(getattr(block, "to_dict", None)):
                    serialized_content.append(block.to_dict())
                elif callable(getattr(block, "model_dump", None)):
                    serialized_content.append(block.model_dump())
                elif isinstance(block, dict):
                    serialized_content.append(block)
                else:
                    serialized_content.append({"type": "text", "text": str(block)})
            return {"role": self.role, "content": serialized_content}
        return {"role": self.role, "content": self.content}
