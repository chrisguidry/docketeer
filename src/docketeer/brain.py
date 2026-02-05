"""Claude reasoning loop with tool use."""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import anthropic

from docketeer.config import Config
from docketeer.tools import WORKSPACE_TOOLS, ToolExecutor

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Nix, a helpful assistant in a Rocket Chat server for the Guidry family.

Current time: {current_time}

Keep responses concise and friendly. You're part of the family chat, not a formal assistant.

You have access to a workspace directory where you can read and write files.
Use the workspace tools to help manage notes, lists, and other text files for the family.
"""

HISTORY_LIMIT = 20
MAX_TOOL_ROUNDS = 10


@dataclass
class MessageContent:
    """Content to send to Claude - text and/or images."""
    username: str
    text: str = ""
    images: list[tuple[str, bytes]] = None

    def __post_init__(self):
        if self.images is None:
            self.images = []


@dataclass
class HistoryMessage:
    """A message from conversation history."""
    role: str
    username: str
    text: str


@dataclass
class ToolCall:
    """Record of a tool call for reporting to the user."""
    name: str
    args: dict[str, Any]
    result: str
    is_error: bool = False


@dataclass
class BrainResponse:
    """Response from Brain including tool calls made."""
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class Brain:
    def __init__(self, config: Config, tool_executor: ToolExecutor):
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.tool_executor = tool_executor
        self._conversations: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def load_history(self, room_id: str, messages: list[HistoryMessage]) -> int:
        """Load conversation history for a room. Returns count loaded."""
        for msg in messages:
            if msg.role == "user":
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

    async def process(self, room_id: str, content: MessageContent) -> BrainResponse:
        """Process a message and return a response with tool call info."""
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        system = SYSTEM_PROMPT.format(current_time=current_time)

        # Build content for the user message
        user_content = self._build_content(content)

        # Add to conversation history
        self._conversations[room_id].append({"role": "user", "content": user_content})

        # Get trimmed messages for API call
        messages = self._conversations[room_id][-HISTORY_LIMIT * 2:]

        log.debug("Processing message with %d history messages", len(messages))

        # Agentic loop: keep calling Claude until no more tool use
        tool_calls = []
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=self.config.claude_model,
                max_tokens=1024,
                system=system,
                messages=messages,
                tools=WORKSPACE_TOOLS,
            )

            # Check if we need to handle tool use
            if response.stop_reason == "tool_use":
                # Process all tool uses in this response
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        log.info("Tool call: %s(%s)", block.name, block.input)
                        result = await self.tool_executor.execute(block.name, block.input)
                        is_error = result.startswith("Error:")
                        log.info("Tool result: %s", result[:100])

                        tool_calls.append(ToolCall(
                            name=block.name,
                            args=block.input,
                            result=result,
                            is_error=is_error,
                        ))

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                            "is_error": is_error,
                        })

                # Add assistant message and tool results to conversation
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                # No more tool use, extract final text response
                break

        # Extract text from final response
        reply_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                reply_parts.append(block.text)

        reply = "\n".join(reply_parts) if reply_parts else "(no response)"

        # Add final response to conversation history
        self._conversations[room_id].append({"role": "assistant", "content": reply})

        log.debug("Response: %s", reply[:100])
        return BrainResponse(text=reply, tool_calls=tool_calls)

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

        text = f"@{content.username}: {content.text}" if content.text else ""

        if text:
            blocks.append({"type": "text", "text": text})

        if not blocks:
            blocks.append({"type": "text", "text": f"@{content.username}: (empty message)"})

        if len(blocks) == 1 and blocks[0]["type"] == "text":
            return text or f"@{content.username}: (empty message)"

        return blocks
