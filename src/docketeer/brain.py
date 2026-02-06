"""Claude reasoning loop with tool use."""

import importlib.resources
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from docketeer.config import Config
from docketeer.tools import ToolContext, registry

log = logging.getLogger(__name__)

HISTORY_LIMIT = 20
MAX_TOOL_ROUNDS = 10


def _ensure_template(workspace: Path, filename: str) -> None:
    """Copy a template from the package to the workspace if it doesn't exist."""
    stem, ext = filename.rsplit(".", 1)
    target = workspace / f"{stem.upper()}.{ext}"
    if target.exists():
        return
    source = importlib.resources.files("docketeer").joinpath(filename)
    target.write_text(source.read_text())
    log.info("Copied %s template to %s", filename, target)


def _load_system_prompt(workspace: Path, current_time: str, username: str) -> str:
    """Build system prompt from SOUL.md and optionally BOOTSTRAP.md."""
    soul_path = workspace / "SOUL.md"
    prompt = soul_path.read_text().format(current_time=current_time, username=username)

    bootstrap_path = workspace / "BOOTSTRAP.md"
    if bootstrap_path.exists():
        prompt += "\n\n" + bootstrap_path.read_text()

    return prompt


def _audit_log(audit_dir: Path, tool_name: str, args: dict, result: str, is_error: bool) -> None:
    """Append a tool call record to today's audit log."""
    now = datetime.now(timezone.utc)
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{now.strftime('%Y-%m-%d')}.jsonl"

    record = {
        "ts": now.isoformat(),
        "tool": tool_name,
        "args": args,
        "result_length": len(result),
        "is_error": is_error,
    }
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


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
class BrainResponse:
    """Response from Brain."""
    text: str


class Brain:
    def __init__(self, config: Config, tool_context: ToolContext):
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self.tool_context = tool_context
        self._conversations: dict[str, list[dict[str, Any]]] = defaultdict(list)

        soul_path = config.workspace_path / "SOUL.md"
        first_run = not soul_path.exists()
        _ensure_template(config.workspace_path, "soul.md")
        if first_run:
            _ensure_template(config.workspace_path, "bootstrap.md")

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
        current_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
        system = _load_system_prompt(
            self.config.workspace_path, current_time, content.username
        )

        # Update tool context with current username
        self.tool_context.username = content.username

        # Build content for the user message
        user_content = self._build_content(content)

        # Add to conversation history
        self._conversations[room_id].append({"role": "user", "content": user_content})

        # Get trimmed messages for API call
        messages = self._conversations[room_id][-HISTORY_LIMIT * 2:]

        log.debug("Processing message with %d history messages", len(messages))

        # Agentic loop: keep calling Claude until no more tool use
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=self.config.claude_model,
                max_tokens=1024,
                system=system,
                messages=messages,
                tools=registry.definitions(),
            )

            # Check if we need to handle tool use
            if response.stop_reason == "tool_use":
                # Process all tool uses in this response
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        log.info("Tool call: %s(%s)", block.name, block.input)
                        result = await registry.execute(
                            block.name, block.input, self.tool_context
                        )
                        is_error = result.startswith("Error:")
                        log.info("Tool result: %s", result[:100])

                        _audit_log(
                            self.config.audit_path,
                            block.name, block.input, result, is_error,
                        )

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
        return BrainResponse(text=reply)

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
