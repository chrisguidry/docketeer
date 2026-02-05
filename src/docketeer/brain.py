"""Claude reasoning loop - pure reasoning, no I/O."""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

import anthropic

from docketeer.config import Config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Nix, a helpful assistant in a Rocket Chat server for the Guidry family.

Current time: {current_time}

Keep responses concise and friendly. You're part of the family chat, not a formal assistant.
"""

HISTORY_LIMIT = 20


@dataclass
class MessageContent:
    """Content to send to Claude - text and/or images."""
    username: str
    text: str = ""
    images: list[tuple[str, bytes]] = None  # (media_type, data) pairs

    def __post_init__(self):
        if self.images is None:
            self.images = []


@dataclass
class HistoryMessage:
    """A message from conversation history."""
    role: str  # "user" or "assistant"
    username: str
    text: str


class Brain:
    def __init__(self, config: Config):
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._conversations: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def load_history(self, room_id: str, messages: list[HistoryMessage]) -> int:
        """Load conversation history for a room. Returns count loaded."""
        for msg in messages:
            if msg.role == "user":
                # Include username for multi-user context
                content = f"@{msg.username}: {msg.text}"
            else:
                content = msg.text
            self._conversations[room_id].append({
                "role": msg.role,
                "content": content,
            })
        return len(messages)

    def has_history(self, room_id: str) -> bool:
        """Check if we have history for a room."""
        return room_id in self._conversations

    def process(self, room_id: str, content: MessageContent) -> str:
        """Process a message and return a response."""
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        system = SYSTEM_PROMPT.format(current_time=current_time)

        # Build content blocks for Claude
        claude_content = self._build_content(content)

        # Add to conversation
        self._conversations[room_id].append({"role": "user", "content": claude_content})

        # Trim to keep conversation manageable
        messages = self._conversations[room_id][-HISTORY_LIMIT * 2:]

        log.debug("Sending %d messages to Claude", len(messages))

        response = self.client.messages.create(
            model=self.config.claude_model,
            max_tokens=1024,
            system=system,
            messages=messages,
        )

        reply = response.content[0].text

        # Add response to conversation history
        self._conversations[room_id].append({"role": "assistant", "content": reply})

        log.debug("Claude response: %s", reply)
        return reply

    def _build_content(self, content: MessageContent) -> list[dict] | str:
        """Build content blocks for Claude."""
        blocks = []

        for media_type, data in content.images:
            import base64
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(data).decode("utf-8"),
                },
            })

        # Prefix text with username for multi-user context
        text = f"@{content.username}: {content.text}" if content.text else ""

        if text:
            blocks.append({"type": "text", "text": text})

        if not blocks:
            blocks.append({"type": "text", "text": f"@{content.username}: (empty message)"})

        # If just text, return as string for simpler history
        if len(blocks) == 1 and blocks[0]["type"] == "text":
            return text or f"@{content.username}: (empty message)"

        return blocks
