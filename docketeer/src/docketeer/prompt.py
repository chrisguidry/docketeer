"""System prompt construction and shared message types."""

import importlib.resources
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


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

    role: str
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
) -> list[dict]:
    """Build system prompt as content blocks for prompt caching.

    The stable SOUL.md content is cached; the dynamic time/username/person
    context block is not (but saves tool calls Nix would otherwise make).
    """
    soul_path = workspace / "SOUL.md"
    stable_text = soul_path.read_text()

    bootstrap_path = workspace / "BOOTSTRAP.md"
    if bootstrap_path.exists():
        stable_text += "\n\n" + bootstrap_path.read_text()

    blocks = [
        {
            "type": "text",
            "text": stable_text,
            "cache_control": {"type": "ephemeral"},
        },
    ]

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

    blocks.append({"type": "text", "text": "\n".join(dynamic_parts)})

    return blocks


def extract_text(content: str | list) -> str:
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
