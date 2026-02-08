"""Claude reasoning loop with tool use."""

import base64
import json
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import anthropic
from anthropic.types import (
    Base64ImageSourceParam,
    CacheControlEphemeralParam,
    ContentBlockParam,
    ImageBlockParam,
    MessageParam,
    TextBlock,
    TextBlockParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlock,
)

from docketeer import environment
from docketeer.people import build_person_map, load_person_context
from docketeer.prompt import (
    BrainResponse,
    HistoryMessage,
    MessageContent,
    RoomInfo,
    SystemBlock,
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
    cr = getattr(u, "cache_read_input_tokens", 0) or 0
    cw = getattr(u, "cache_creation_input_tokens", 0) or 0
    log.info(
        "Tokens: %d in (%d cache-read, %d cache-write, %d uncached), %d out",
        cr + cw + u.input_tokens,
        cr,
        cw,
        u.input_tokens,
        u.output_tokens,
    )


class Brain:
    def __init__(self, tool_context: ToolContext) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        self.tool_context = tool_context
        self._workspace = tool_context.workspace
        self._audit_path = tool_context.workspace.parent / "audit"
        self._conversations: dict[str, list[MessageParam]] = defaultdict(list)
        self._room_token_counts: dict[str, int] = {}
        self._room_info: dict[str, RoomInfo] = {}
        self._person_map: dict[str, str] = {}

        soul_path = self._workspace / "SOUL.md"
        first_run = not soul_path.exists()
        ensure_template(self._workspace, "soul.md")
        if first_run:
            ensure_template(self._workspace, "bootstrap.md")

        ensure_template(self._workspace, "cycles.md")

        self.tool_context.summarize = self._summarize_webpage
        self.tool_context.classify_response = self._classify_response

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
                MessageParam(role=msg.role, content=content)
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
            tools[-1]["cache_control"] = CacheControlEphemeralParam(type="ephemeral")

        # Update tool context with current message info
        self.tool_context.username = content.username
        self.tool_context.room_id = room_id

        # Compact if we're approaching the context limit
        if self._room_token_counts.get(room_id, 0) > COMPACT_THRESHOLD:
            await self._compact_history(room_id, system, tools)

        # Build content for the user message
        user_content = self._build_content(content)

        # Add to conversation history
        self._conversations[room_id].append(
            MessageParam(role="user", content=user_content)
        )

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
                messages.append(
                    MessageParam(role="assistant", content=response.content)
                )
                messages.append(MessageParam(role="user", content=tool_results))
            elif response.stop_reason == "max_tokens":
                log.warning("Response truncated at %d tokens", MAX_RESPONSE_TOKENS)
                break
            else:
                break

        reply = self._build_reply(response, used_tools, rounds)

        if reply:
            self._conversations[room_id].append(
                MessageParam(role="assistant", content=reply)
            )

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
        system: list[SystemBlock],
        messages: list[MessageParam],
        tools: list[ToolParam],
        on_first_text: Callable[[], Awaitable[None]] | None = None,
    ) -> anthropic.types.Message:
        """Stream a response from Claude, optionally firing a callback on first text."""
        async with self.client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=[b.to_api_dict() for b in system],
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
    ) -> list[ToolResultBlockParam]:
        """Run each tool, log calls/results, write audit log, return tool_result dicts."""
        tool_results: list[ToolResultBlockParam] = []
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
        self, messages: list[MessageParam], tool_results: list[ToolResultBlockParam]
    ) -> None:
        """Move the cache breakpoint to the latest tool result."""
        for prev_msg in messages:
            if prev_msg["role"] != "user" or not isinstance(prev_msg["content"], list):
                continue
            for block in prev_msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    block.pop("cache_control", None)  # type: ignore[misc]

        tool_results[-1]["cache_control"] = CacheControlEphemeralParam(type="ephemeral")

    def _build_reply(
        self, response: anthropic.types.Message, had_tool_use: bool, rounds: int
    ) -> str:
        """Extract the final reply text from a response."""
        reply_parts = [
            block.text for block in response.content if isinstance(block, TextBlock)
        ]

        if response.stop_reason == "max_tokens" and not had_tool_use:
            reply_parts.append(
                "\n\n(I hit my response length limit — ask me to continue if I got cut off)"
            )

        if not reply_parts:
            if had_tool_use:
                log.info("Tool-only response, no text to send (rounds=%d)", rounds)
                return ""
            types = [getattr(b, "type", type(b).__name__) for b in response.content]
            log.warning(
                "No text in response: stop=%s, blocks=%s, rounds=%d/%d",
                response.stop_reason,
                types,
                rounds,
                MAX_TOOL_ROUNDS,
            )
            return "(no response)"

        return "\n".join(reply_parts).strip()

    async def _measure_context(
        self, room_id: str, system: list[SystemBlock], tools: list[ToolParam]
    ) -> int:
        """Count tokens for the current conversation state."""
        result = await self.client.messages.count_tokens(
            model=CLAUDE_MODEL,
            system=[b.to_api_dict() for b in system],
            tools=tools,
            messages=self._conversations[room_id],
        )
        self._room_token_counts[room_id] = result.input_tokens
        return result.input_tokens

    async def _compact_history(
        self, room_id: str, system: list[SystemBlock], tools: list[ToolParam]
    ) -> None:
        """Summarize older messages to free up context space."""
        messages = self._conversations[room_id]
        if len(messages) <= MIN_RECENT_MESSAGES:
            return

        old_count = len(messages)
        old_messages = messages[:-MIN_RECENT_MESSAGES]
        recent_messages = messages[-MIN_RECENT_MESSAGES:]

        # Build a transcript of the old messages for summarization
        transcript = "\n".join(
            f"{msg['role']}: {text}"
            for msg in old_messages
            if (text := extract_text(msg["content"]))
        )

        if not transcript.strip():
            return

        summary = await self._summarize_transcript(transcript)
        if summary is None:
            self._conversations[room_id] = recent_messages
            return

        self._conversations[room_id] = [
            MessageParam(
                role="user",
                content=f"[Earlier conversation summary]\n{summary}",
            ),
            MessageParam(role="assistant", content="Got it, I have that context."),
            *recent_messages,
        ]

        tokens = await self._measure_context(room_id, system, tools)
        log.info(
            "Compacted room %s: %d → %d messages (%d tokens)",
            room_id,
            old_count,
            len(self._conversations[room_id]),
            tokens,
        )

    async def _summarize_transcript(self, transcript: str) -> str | None:
        """Ask Haiku for a conversation summary, or None on failure."""
        try:
            summary_response = await self.client.messages.create(
                model=COMPACT_MODEL,
                max_tokens=1024,
                messages=[
                    MessageParam(
                        role="user",
                        content=(
                            "Summarize this conversation into a concise recap. "
                            "Preserve key facts, decisions, and context that would "
                            "be needed to continue the conversation naturally. "
                            "Be brief but thorough.\n\n"
                            f"{transcript}"
                        ),
                    )
                ],
            )
            block = summary_response.content[0]
            return block.text if isinstance(block, TextBlock) else str(block)
        except Exception:
            log.exception("Summarization failed, falling back to truncation")
            return None

    async def _summarize_webpage(self, text: str, purpose: str) -> str:
        """Ask Haiku to summarize a web page, guided by the fetch purpose."""
        focus = f" for someone who wants to: {purpose}" if purpose else ""
        response = await self.client.messages.create(
            model=COMPACT_MODEL,
            max_tokens=2048,
            messages=[
                MessageParam(
                    role="user",
                    content=(
                        f"Summarize this web page{focus}. "
                        "Preserve key facts, URLs, numbers, and any structured data. "
                        "Omit navigation, ads, and boilerplate.\n\n"
                        f"{text}"
                    ),
                )
            ],
        )
        block = response.content[0]
        return block.text if isinstance(block, TextBlock) else str(block)

    async def _classify_response(
        self, url: str, status_code: int, headers: str
    ) -> bool:
        """Ask Haiku whether an HTTP response body is likely readable text."""
        response = await self.client.messages.create(
            model=COMPACT_MODEL,
            max_tokens=8,
            messages=[
                MessageParam(
                    role="user",
                    content=(
                        "Given this HTTP response, is the body likely readable text "
                        "(HTML, JSON, plain text, etc.) that would be useful to read? "
                        "Answer only 'true' or 'false'.\n\n"
                        f"URL: {url}\n"
                        f"Status: {status_code}\n"
                        f"Headers:\n{headers}"
                    ),
                )
            ],
        )
        block = response.content[0]
        answer = block.text if isinstance(block, TextBlock) else ""
        return answer.strip().lower() == "true"

    def _build_content(self, content: MessageContent) -> list[ContentBlockParam] | str:
        """Build content blocks for Claude."""
        blocks: list[ContentBlockParam] = []
        prefix = f"[{content.timestamp}] " if content.timestamp else ""
        empty = f"{prefix}@{content.username}: (empty message)"

        for media_type, data in content.images:
            blocks.append(
                ImageBlockParam(
                    type="image",
                    source=Base64ImageSourceParam(
                        type="base64",
                        media_type=media_type,  # type: ignore[arg-type]
                        data=base64.b64encode(data).decode("utf-8"),
                    ),
                )
            )

        text = f"{prefix}@{content.username}: {content.text}" if content.text else ""

        if text:
            blocks.append(TextBlockParam(type="text", text=text))
        elif not blocks:
            blocks.append(TextBlockParam(type="text", text=empty))

        if len(blocks) == 1 and blocks[0]["type"] == "text":
            return text or empty

        return blocks
