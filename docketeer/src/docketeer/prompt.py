"""System prompt construction and shared message types."""

import importlib.resources
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from anthropic.types import CacheControlEphemeralParam, TextBlockParam

from docketeer.chat import RoomInfo, RoomKind  # noqa: F401
from docketeer.plugins import discover_all

log = logging.getLogger(__name__)


@dataclass
class CacheControl:
    """Prompt caching control."""

    ttl: Literal["5m", "1h"] = "5m"

    def to_api_dict(self) -> CacheControlEphemeralParam:
        return CacheControlEphemeralParam(type="ephemeral", ttl=self.ttl)


@dataclass
class SystemBlock:
    """A text block in the system prompt."""

    text: str
    cache_control: CacheControl | None = None

    def to_api_dict(self) -> TextBlockParam:
        """Serialize for the Anthropic API system parameter."""
        d = TextBlockParam(type="text", text=self.text)
        if self.cache_control:
            d["cache_control"] = self.cache_control.to_api_dict()
        return d


def _load_prompt_providers() -> list[Callable[[Path], list[SystemBlock]]]:
    return discover_all("docketeer.prompt")


_prompt_providers = _load_prompt_providers()


@dataclass
class MessageContent:
    """Content to send to Claude - text and/or images."""

    username: str
    message_id: str = ""
    timestamp: str = ""
    text: str = ""
    thread_id: str = ""
    images: list[tuple[str, bytes]] = field(default_factory=list)


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
    person_context: str = "",
    room_info: RoomInfo | None = None,
) -> str:
    """Build per-request dynamic context to prepend to the user message.

    Kept out of the system prompt so that tools + system form a stable
    cacheable prefix.
    """
    parts = [f"Current time: {current_time}"]
    if room_info:
        others = [m for m in room_info.members if m != username]
        match room_info.kind:
            case RoomKind.direct:
                label = f"DM with @{others[0]}" if others else "DM"
            case RoomKind.group:
                label = f"group DM with @{', @'.join(others)}" if others else "group DM"
            case RoomKind.private:
                name = f"#{room_info.name}" if room_info.name else "private channel"
                label = (
                    f"{name} (private, with @{', @'.join(others)})" if others else name
                )
            case RoomKind.public:
                name = f"#{room_info.name}" if room_info.name else "channel"
                label = f"{name} (with @{', @'.join(others)})" if others else name
            case _:  # pragma: no cover
                label = room_info.name or room_info.room_id
        parts.append(f"Room: {label}")

    parts.append(f"Talking to: @{username}")

    if person_context:
        parts.append(f"\n## What I know about @{username}\n\n{person_context}")

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
