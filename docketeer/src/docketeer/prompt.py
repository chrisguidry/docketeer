"""System prompt construction and shared message types."""

import importlib.resources
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Literal

from anthropic.types import CacheControlEphemeralParam, TextBlockParam

log = logging.getLogger(__name__)


@dataclass
class SystemBlock:
    """A text block in the system prompt."""

    text: str
    cache_control: CacheControlEphemeralParam | None = None

    def to_api_dict(self) -> TextBlockParam:
        """Serialize for the Anthropic API system parameter."""
        d = TextBlockParam(type="text", text=self.text)
        if self.cache_control:
            d["cache_control"] = self.cache_control
        return d


def _load_prompt_providers() -> list[Callable[[Path], list[SystemBlock]]]:
    providers = []
    for ep in entry_points(group="docketeer.prompt"):
        try:
            providers.append(ep.load())
        except Exception:
            log.warning("Failed to load prompt plugin: %s", ep.name, exc_info=True)
    return providers


_prompt_providers = _load_prompt_providers()


@dataclass
class RoomInfo:
    """Metadata about the room the agent is operating in."""

    room_id: str
    is_direct: bool
    members: list[str]
    name: str = ""


@dataclass
class MessageContent:
    """Content to send to Claude - text and/or images."""

    username: str
    timestamp: str = ""
    text: str = ""
    images: list[tuple[str, bytes]] = field(default_factory=list)


@dataclass
class HistoryMessage:
    """A message from conversation history."""

    role: Literal["user", "assistant"]
    username: str
    text: str
    timestamp: str = ""


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


def build_system_blocks(
    workspace: Path,
    current_time: str,
    username: str,
    person_context: str = "",
    room_info: RoomInfo | None = None,
) -> list[SystemBlock]:
    """Build system prompt as content blocks for prompt caching.

    The stable SOUL.md content is cached; the dynamic time/username/person
    context block is not (but saves tool calls Nix would otherwise make).
    """
    soul_path = workspace / "SOUL.md"
    stable_text = soul_path.read_text()

    bootstrap_path = workspace / "BOOTSTRAP.md"
    if bootstrap_path.exists():
        stable_text += "\n\n" + bootstrap_path.read_text()

    blocks: list[SystemBlock] = [
        SystemBlock(
            text=stable_text,
            cache_control=CacheControlEphemeralParam(type="ephemeral"),
        ),
    ]

    for provider in _prompt_providers:
        try:
            blocks.extend(provider(workspace))
        except Exception:
            log.warning("Prompt provider %s failed", provider, exc_info=True)

    dynamic_parts = [f"Current time: {current_time}"]
    if room_info:
        others = [m for m in room_info.members if m != username]
        if room_info.is_direct:
            label = f"DM with @{others[0]}" if others else "DM"
        else:
            name = f"#{room_info.name}" if room_info.name else "group chat"
            label = f"{name} (with @{', @'.join(others)})" if others else name
        dynamic_parts.append(f"Room: {label}")

    dynamic_parts.append(f"Talking to: @{username}")

    if person_context:
        dynamic_parts.append(f"\n## What I know about @{username}\n\n{person_context}")

    blocks.append(SystemBlock(text="\n".join(dynamic_parts)))

    return blocks


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
