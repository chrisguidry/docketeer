"""Claude reasoning loop with tool use."""

import base64
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import anthropic
from anthropic.types import ToolUseBlock

from docketeer import environment
from docketeer.people import build_person_map, load_person_context
from docketeer.prompt import (
    BrainResponse,
    HistoryMessage,
    MessageContent,
    RoomInfo,
    build_system_blocks,
    ensure_template,
    extract_text,
)
from docketeer.tools import ToolContext, registry

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = environment.get_str("ANTHROPIC_API_KEY")
CLAUDE_MODEL = environment.get_str("CLAUDE_MODEL", "claude-opus-4-6")

MAX_TOOL_ROUNDS = 10
MAX_RESPONSE_TOKENS = 128_000
CONTEXT_BUDGET = 180_000
COMPACT_THRESHOLD = 140_000
COMPACT_MODEL = "claude-haiku-4-5-20251001"
MIN_RECENT_MESSAGES = 6


@dataclass
class ProcessCallbacks:
    """Optional callbacks fired during process() for typing/presence signals."""

    on_first_text: Callable[[], Awaitable[None]] | None = None
    on_tool_start: Callable[[], Awaitable[None]] | None = None
    on_tool_end: Callable[[], Awaitable[None]] | None = None


def _audit_log(
    audit_dir: Path, tool_name: str, args: dict, result: str, is_error: bool
) -> None:
    """Append a tool call record to today's audit log."""
    now = datetime.now(UTC)
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
        cache_read,
        cache_write,
        u.input_tokens,
        u.output_tokens,
    )


class Brain:
    def __init__(self, tool_context: ToolContext) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        self.tool_context = tool_context
        self._workspace = tool_context.workspace
        self._audit_path = tool_context.workspace.parent / "audit"
        self._conversations: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._room_token_counts: dict[str, int] = {}
        self._room_info: dict[str, RoomInfo] = {}
        self._person_map: dict[str, str] = {}

        soul_path = self._workspace / "SOUL.md"
        first_run = not soul_path.exists()
        ensure_template(self._workspace, "soul.md")
        if first_run:
            ensure_template(self._workspace, "bootstrap.md")

        ensure_template(self._workspace, "cycles.md")

        self._person_map = build_person_map(self._workspace)
        log.info("Person map: %s", self._person_map)

    def set_room_info(self, room_id: str, info: RoomInfo) -> None:
        """Store metadata about a room for use in the system prompt."""
        self._room_info[room_id] = info

    def rebuild_person_map(self) -> None:
        """Rebuild the username→person-file mapping after a people/ write."""
        self._person_map = build_person_map(self._workspace)
        log.info("Rebuilt person map: %s", self._person_map)

    def load_history(self, room_id: str, messages: list[HistoryMessage]) -> int:
        """Load conversation history for a room. Returns count loaded."""
        for msg in messages:
            if msg.role == "user":
                prefix = f"[{msg.timestamp}] " if msg.timestamp else ""
                content = f"{prefix}@{msg.username}: {msg.text}"
            else:
                content = msg.text
            self._conversations[room_id].append(
                {
                    "role": msg.role,
                    "content": content,
                }
            )
        return len(messages)

    def has_history(self, room_id: str) -> bool:
        """Check if we have history for a room."""
        return room_id in self._conversations

    async def process(
        self,
        room_id: str,
        content: MessageContent,
        callbacks: ProcessCallbacks | None = None,
    ) -> BrainResponse:
        """Process a message and return a response with tool call info."""
        current_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
        person_context = load_person_context(
            self._workspace,
            content.username,
            self._person_map,
        )
        room_info = self._room_info.get(room_id)
        system = build_system_blocks(
            self._workspace,
            current_time,
            content.username,
            person_context=person_context,
            room_info=room_info,
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
        on_first_text = callbacks.on_first_text if callbacks else None
        used_tools = False
        rounds = 0
        for _ in range(MAX_TOOL_ROUNDS):
            rounds += 1
            response = await self._stream_message(
                system, messages, tools, on_first_text=on_first_text
            )

            _log_usage(response)

            # Process any tool_use blocks, even if the response was truncated
            tool_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]

            if tool_blocks:
                used_tools = True
                if callbacks and callbacks.on_tool_start:
                    await callbacks.on_tool_start()
                tool_results = await self._execute_tools(tool_blocks)
                if callbacks and callbacks.on_tool_end:
                    await callbacks.on_tool_end()
                self._update_cache_breakpoints(messages, tool_results)
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            elif response.stop_reason == "max_tokens":
                log.warning("Response truncated at %d tokens", MAX_RESPONSE_TOKENS)
                break
            else:
                break

        reply = self._build_reply(response, used_tools, rounds)

        if reply:
            self._conversations[room_id].append({"role": "assistant", "content": reply})

        tokens = await self._measure_context(room_id, system, tools)
        log.info(
            "Context: %d / %d tokens for room %s",
            tokens,
            CONTEXT_BUDGET,
            room_id,
        )

        log.debug("Response: %s", reply[:100])
        return BrainResponse(text=reply)

    async def _stream_message(
        self,
        system: Any,
        messages: Any,
        tools: Any,
        on_first_text: Callable[[], Awaitable[None]] | None = None,
    ) -> anthropic.types.Message:
        """Stream a response from Claude, optionally firing a callback on first text."""
        async with self.client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            if on_first_text:
                async for _text in stream.text_stream:
                    await on_first_text()
                    break
            return await stream.get_final_message()

    async def _execute_tools(
        self, tool_blocks: list[ToolUseBlock]
    ) -> list[dict[str, Any]]:
        """Run each tool, log calls/results, write audit log, return tool_result dicts."""
        tool_results = []
        for block in tool_blocks:
            log.info("Tool call: %s(%s)", block.name, block.input)
            result = await registry.execute(block.name, block.input, self.tool_context)
            is_error = result.startswith("Error:")
            log.info("Tool result: %s", result[:100])

            _audit_log(
                self._audit_path,
                block.name,
                block.input,
                result,
                is_error,
            )

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                    "is_error": is_error,
                }
            )
        return tool_results

    def _update_cache_breakpoints(
        self, messages: list[dict[str, Any]], tool_results: list[dict[str, Any]]
    ) -> None:
        """Move the cache breakpoint to the latest tool result.

        Strips any previous tool-result breakpoints first to stay within the
        API's 4-breakpoint limit.
        """
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

    def _build_reply(
        self, response: anthropic.types.Message, had_tool_use: bool, rounds: int
    ) -> str:
        """Extract the final reply text from a response."""
        reply_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                reply_parts.append(block.text)

        if response.stop_reason == "max_tokens" and not had_tool_use:
            reply_parts.append(
                "\n\n(I hit my response length limit — ask me to continue if I got cut off)"
            )

        if not reply_parts:
            if had_tool_use:
                log.info("Tool-only response, no text to send (rounds=%d)", rounds)
                return ""
            block_types = [
                getattr(b, "type", type(b).__name__) for b in response.content
            ]
            log.warning(
                "No text in response: stop_reason=%s, blocks=%s, rounds=%d/%d",
                response.stop_reason,
                block_types,
                rounds,
                MAX_TOOL_ROUNDS,
            )
            return "(no response)"

        return "\n".join(reply_parts).strip()

    async def _measure_context(self, room_id: str, system: Any, tools: Any) -> int:
        """Count tokens for the current conversation state."""
        result = await self.client.messages.count_tokens(
            model=CLAUDE_MODEL,
            system=system,
            tools=tools,
            messages=cast(Any, self._conversations[room_id]),
        )
        self._room_token_counts[room_id] = result.input_tokens
        return result.input_tokens

    async def _compact_history(self, room_id: str, system: Any, tools: Any) -> None:
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
            text = extract_text(msg["content"])
            if text:
                transcript_lines.append(f"{msg['role']}: {text}")
        transcript = "\n".join(transcript_lines)

        if not transcript.strip():
            return

        summary = await self._summarize_transcript(transcript)
        if summary is None:
            self._conversations[room_id] = recent_messages
            return

        self._conversations[room_id] = [
            {"role": "user", "content": f"[Earlier conversation summary]\n{summary}"},
            {"role": "assistant", "content": "Got it, I have that context."},
            *recent_messages,
        ]

        new_count = len(self._conversations[room_id])
        tokens = await self._measure_context(room_id, system, tools)
        log.info(
            "Compacted room %s: %d messages → %d (%d tokens)",
            room_id,
            old_count,
            new_count,
            tokens,
        )

    async def _summarize_transcript(self, transcript: str) -> str | None:
        """Ask Haiku for a conversation summary, or None on failure."""
        try:
            summary_response = await self.client.messages.create(
                model=COMPACT_MODEL,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Summarize this conversation into a concise recap. "
                            "Preserve key facts, decisions, and context that would "
                            "be needed to continue the conversation naturally. "
                            "Be brief but thorough.\n\n"
                            f"{transcript}"
                        ),
                    }
                ],
            )
            first_block = summary_response.content[0]
            text = (
                first_block.text if hasattr(first_block, "text") else str(first_block)
            )
            return str(text)
        except Exception:
            log.exception("Summarization failed, falling back to truncation")
            return None

    def _build_content(self, content: MessageContent) -> list[dict] | str:
        """Build content blocks for Claude."""
        blocks = []
        prefix = f"[{content.timestamp}] " if content.timestamp else ""

        for media_type, data in content.images:
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(data).decode("utf-8"),
                    },
                }
            )

        text = f"{prefix}@{content.username}: {content.text}" if content.text else ""

        if text:
            blocks.append({"type": "text", "text": text})

        if not blocks:
            blocks.append(
                {
                    "type": "text",
                    "text": f"{prefix}@{content.username}: (empty message)",
                }
            )

        if len(blocks) == 1 and blocks[0]["type"] == "text":
            return text or f"{prefix}@{content.username}: (empty message)"

        return blocks
