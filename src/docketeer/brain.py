"""Claude reasoning loop with tool use."""

import asyncio
import base64
import importlib.resources
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import anthropic

from docketeer.config import Config
from docketeer.tools import ToolContext, registry

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10
MAX_RESPONSE_TOKENS = 128_000
CONTEXT_BUDGET = 180_000
COMPACT_THRESHOLD = 140_000
MIN_RECENT_MESSAGES = 6


_USERNAME_RE = re.compile(r"\*\*Username:\*\*\s*@(\S+)")


def _build_person_map(workspace: Path) -> dict[str, str]:
    """Scan people/*/profile.md for **Username:** lines, return {rc_username: person_dir}."""
    people_dir = workspace / "people"
    if not people_dir.is_dir():
        return {}
    mapping: dict[str, str] = {}
    for profile in people_dir.glob("*/profile.md"):
        for line in profile.read_text().splitlines():
            if m := _USERNAME_RE.search(line):
                mapping[m.group(1)] = f"people/{profile.parent.name}"
                break
    return mapping


def _load_person_context(
    workspace: Path, username: str, person_map: dict[str, str],
) -> str:
    """Build a context string with the person's profile and recent journal mentions."""
    person_dir = person_map.get(username)
    if not person_dir:
        return ""

    parts: list[str] = []

    profile = workspace / person_dir / "profile.md"
    if profile.exists():
        parts.append(profile.read_text().rstrip())

    # Use the directory name for wikilink matching (e.g. "chris" from "people/chris")
    name = Path(person_dir).name
    wikilink_pattern = f"[[people/{name}]]".lower()

    journal_dir = workspace / "journal"
    if journal_dir.is_dir():
        cutoff = (datetime.now().astimezone() - timedelta(days=7)).strftime("%Y-%m-%d")
        mentions: list[str] = []
        for jpath in sorted(journal_dir.glob("*.md")):
            if jpath.stem < cutoff:
                continue
            for line in jpath.read_text().splitlines():
                if line.startswith("- ") and wikilink_pattern in line.lower():
                    mentions.append(f"[{jpath.stem}] {line}")
        if mentions:
            parts.append("Recent journal mentions:\n" + "\n".join(mentions))

    return "\n\n".join(parts)


def _ensure_template(workspace: Path, filename: str) -> None:
    """Copy a template from the package to the workspace if it doesn't exist."""
    stem, ext = filename.rsplit(".", 1)
    target = workspace / f"{stem.upper()}.{ext}"
    if target.exists():
        return
    source = importlib.resources.files("docketeer").joinpath(filename)
    target.write_text(source.read_text())
    log.info("Copied %s template to %s", filename, target)


def _build_system_blocks(
    workspace: Path, current_time: str, username: str,
    person_context: str = "",
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

    dynamic_parts = [f"Current time: {current_time}", f"Talking to: @{username}"]
    if person_context:
        dynamic_parts.append(f"\n## What I know about @{username}\n\n{person_context}")

    blocks.append({"type": "text", "text": "\n".join(dynamic_parts)})

    return blocks


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


def _log_usage(response: anthropic.types.Message) -> None:
    """Log token usage including cache stats."""
    u = response.usage
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
    log.info(
        "Tokens: %d in (%d cache-read, %d cache-write, %d uncached), %d out",
        cache_read + cache_write + u.input_tokens,
        cache_read, cache_write, u.input_tokens,
        u.output_tokens,
    )


def _extract_text(content: str | list) -> str:
    """Pull plain text from message content, skipping images and tool results."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block["text"])
            elif block.get("type") == "tool_result":
                # Include tool results as brief context
                result = block.get("content", "")
                if isinstance(result, str) and result:
                    parts.append(f"[tool result: {result[:200]}]")
        elif hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)


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
        self._room_token_counts: dict[str, int] = {}
        self._person_map: dict[str, str] = {}

        soul_path = config.workspace_path / "SOUL.md"
        first_run = not soul_path.exists()
        _ensure_template(config.workspace_path, "soul.md")
        if first_run:
            _ensure_template(config.workspace_path, "bootstrap.md")

        self._person_map = _build_person_map(config.workspace_path)
        log.info("Person map: %s", self._person_map)

    def rebuild_person_map(self) -> None:
        """Rebuild the username→person-file mapping after a people/ write."""
        self._person_map = _build_person_map(self.config.workspace_path)
        log.info("Rebuilt person map: %s", self._person_map)

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
        person_context = _load_person_context(
            self.config.workspace_path, content.username, self._person_map,
        )
        system = _build_system_blocks(
            self.config.workspace_path, current_time, content.username,
            person_context=person_context,
        )

        # Tool definitions with cache breakpoint on last definition
        tools = registry.definitions()
        if tools:
            tools = [*tools]
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}

        # Update tool context with current message info
        self.tool_context.username = content.username
        self.tool_context.room_id = room_id

        # Compact if we're approaching the context limit
        if self._room_token_counts.get(room_id, 0) > COMPACT_THRESHOLD:
            await self._compact_history(room_id, system, tools)

        # Build content for the user message
        user_content = self._build_content(content)

        # Add to conversation history
        self._conversations[room_id].append({"role": "user", "content": user_content})

        messages = self._conversations[room_id]

        log.debug("Processing message with %d history messages", len(messages))

        # Agentic loop: keep calling Claude until no more tool use
        for _ in range(MAX_TOOL_ROUNDS):
            response = await asyncio.to_thread(self._stream_message, system, messages, tools)

            _log_usage(response)

            # Process any tool_use blocks, even if the response was truncated
            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            if tool_blocks:
                tool_results = []
                for block in tool_blocks:
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

                # Move cache breakpoint to the latest tool result so
                # subsequent rounds reuse the conversation prefix.
                # Strip any previous tool-result breakpoints first to
                # stay within the API's 4-breakpoint limit.
                for prev_msg in messages:
                    if prev_msg["role"] != "user" or not isinstance(prev_msg["content"], list):
                        continue
                    for block in prev_msg["content"]:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            block.pop("cache_control", None)

                tool_results[-1] = {
                    **tool_results[-1],
                    "cache_control": {"type": "ephemeral"},
                }

                # Add assistant message and tool results to conversation
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            elif response.stop_reason == "max_tokens":
                log.warning("Response truncated at %d tokens", MAX_RESPONSE_TOKENS)
                break
            else:
                break

        # Extract text from final response
        reply_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                reply_parts.append(block.text)

        if response.stop_reason == "max_tokens" and not tool_blocks:
            reply_parts.append("\n\n(I hit my response length limit — ask me to continue if I got cut off)")

        reply = "\n".join(reply_parts) if reply_parts else "(no response)"

        self._conversations[room_id].append({"role": "assistant", "content": reply})

        tokens = self._measure_context(room_id, system, tools)
        log.info(
            "Context: %d / %d tokens for room %s",
            tokens, CONTEXT_BUDGET, room_id,
        )

        log.debug("Response: %s", reply[:100])
        return BrainResponse(text=reply)

    def _stream_message(
        self, system: list[dict], messages: list[dict], tools: list[dict],
    ) -> anthropic.types.Message:
        """Run the synchronous streaming call (meant to be called via asyncio.to_thread)."""
        with self.client.messages.stream(
            model=self.config.claude_model,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            return stream.get_final_message()

    def _measure_context(self, room_id: str, system: list[dict], tools: list[dict]) -> int:
        """Count tokens for the current conversation state."""
        result = self.client.messages.count_tokens(
            model=self.config.claude_model,
            system=system,
            tools=tools,
            messages=self._conversations[room_id],
        )
        self._room_token_counts[room_id] = result.input_tokens
        return result.input_tokens

    async def _compact_history(
        self, room_id: str, system: list[dict], tools: list[dict],
    ) -> None:
        """Summarize older messages to free up context space."""
        messages = self._conversations[room_id]
        if len(messages) <= MIN_RECENT_MESSAGES:
            return

        old_count = len(messages)
        old_messages = messages[:-MIN_RECENT_MESSAGES]
        recent_messages = messages[-MIN_RECENT_MESSAGES:]

        # Build a transcript of the old messages for summarization
        transcript_lines = []
        for msg in old_messages:
            text = _extract_text(msg["content"])
            if text:
                transcript_lines.append(f"{msg['role']}: {text}")
        transcript = "\n".join(transcript_lines)

        if not transcript.strip():
            return

        try:
            summary_response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": (
                        "Summarize this conversation into a concise recap. "
                        "Preserve key facts, decisions, and context that would "
                        "be needed to continue the conversation naturally. "
                        "Be brief but thorough.\n\n"
                        f"{transcript}"
                    ),
                }],
            )
            summary = summary_response.content[0].text
        except Exception:
            log.exception("Summarization failed, falling back to truncation")
            self._conversations[room_id] = recent_messages
            return

        self._conversations[room_id] = [
            {"role": "user", "content": f"[Earlier conversation summary]\n{summary}"},
            {"role": "assistant", "content": "Got it, I have that context."},
            *recent_messages,
        ]

        new_count = len(self._conversations[room_id])
        tokens = self._measure_context(room_id, system, tools)
        log.info(
            "Compacted room %s: %d messages → %d (%d tokens)",
            room_id, old_count, new_count, tokens,
        )

    def _build_content(self, content: MessageContent) -> list[dict] | str:
        """Build content blocks for Claude."""
        blocks = []

        for media_type, data in content.images:
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
