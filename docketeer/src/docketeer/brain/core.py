"""Brain: the Claude reasoning loop with tool use."""

from __future__ import annotations

import asyncio
import base64
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime

from docketeer import environment
from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
    InferenceBackend,
)
from docketeer.brain.compaction import compact_history
from docketeer.brain.helpers import classify_response, summarize_webpage
from docketeer.chat import RoomMessage
from docketeer.executor import CommandExecutor
from docketeer.people import load_person_context
from docketeer.plugins import discover_one
from docketeer.prompt import (
    Base64ImageSourceParam,
    BrainResponse,
    CacheControl,
    ContentBlockParam,
    ImageBlockParam,
    MessageContent,
    MessageParam,
    SystemBlock,
    TextBlockParam,
    build_system_blocks,
    ensure_template,
    format_message_time,
)
from docketeer.tools import ToolContext, ToolDefinition, registry

log = logging.getLogger(__name__)

MAX_LOG_CONTENT_LENGTH = 500


def _format_message_content(content: str | list) -> str:
    """Extract and truncate message content for logging."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        text = "\n".join(parts)
    else:
        text = str(content)

    if len(text) > MAX_LOG_CONTENT_LENGTH:
        return text[:MAX_LOG_CONTENT_LENGTH] + "..."
    return text


def _format_message_for_log(msg: MessageParam) -> str:
    """Format a message for logging (no system prompts)."""
    content = _format_message_content(msg.content)
    tool_calls = msg.tool_calls

    if tool_calls:
        tc_names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
        return f"tools={tc_names}: {content[:200]}"

    # For user messages, extract just the actual text (strip @username: prefix)
    if msg.role == "user" and ": " in content:
        content = content.split(": ", 1)[1]

    return content


@dataclass(frozen=True)
class InferenceModel:
    """Represents a model configuration for inference backends."""

    model_id: str
    max_output_tokens: int
    thinking_budget: int | None = None


# Note: Core doesn't define model mappings. Each backend registers its own
# models via environment variables or internal defaults.
CHAT_MODEL = environment.get_str("CHAT_MODEL", "balanced")
REVERIE_MODEL = environment.get_str("REVERIE_MODEL", "balanced")
CONSOLIDATION_MODEL = environment.get_str("CONSOLIDATION_MODEL", "balanced")


CONTEXT_BUDGET = 180_000
COMPACT_THRESHOLD = 140_000

APOLOGY = (
    "I'm sorry, I ran into a temporary problem and couldn't finish processing that. "
    "Could you try again in a moment?"
)


def _create_backend(
    executor: CommandExecutor | None = None,
) -> InferenceBackend:
    """Create the inference backend using the plugin discovery system."""
    ep = discover_one("docketeer.inference", "INFERENCE")
    if ep is None:
        raise RuntimeError(
            "No inference backend plugin installed. "
            "Install one such as docketeer-anthropic."
        )

    backend_factory = ep.load()
    return backend_factory(executor=executor)


@dataclass
class ProcessCallbacks:
    """Optional callbacks fired during process() for typing/presence signals."""

    on_first_text: Callable[[], Awaitable[None]] | None = None
    on_text: Callable[[str], Awaitable[None]] | None = None
    on_tool_start: Callable[[str], Awaitable[None]] | None = None
    on_tool_end: Callable[[], Awaitable[None]] | None = None
    interrupted: asyncio.Event | None = None


class Brain:
    def __init__(self, tool_context: ToolContext) -> None:
        self._backend = _create_backend(executor=tool_context.executor)
        self.tool_context = tool_context
        self._workspace = tool_context.workspace
        self._audit_path = tool_context.workspace.parent / "audit"
        self._usage_path = tool_context.workspace.parent / "token-usage"
        self._conversations: dict[str, list[MessageParam]] = defaultdict(list)
        self._conversation_locks: defaultdict[str, asyncio.Lock] = defaultdict(
            asyncio.Lock
        )
        self._room_token_counts: dict[str, int] = {}
        self._last_user_timestamp: dict[str, datetime] = {}
        self._profiles_loaded: dict[str, set[str]] = defaultdict(set)

        soul_path = self._workspace / "SOUL.md"
        first_run = not soul_path.exists()
        ensure_template(self._workspace, "soul.md")
        if first_run:
            ensure_template(self._workspace, "bootstrap.md")

        ensure_template(self._workspace, "practice.md")

        self.tool_context.summarize = self._summarize_webpage
        self.tool_context.classify_response = self._classify_response

    async def __aenter__(self) -> Brain:
        self._stack = AsyncExitStack()
        await self._stack.enter_async_context(self._backend)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    def load_history(self, room_id: str, messages: list[RoomMessage]) -> int:
        """Load conversation history for a room. Returns count loaded."""
        agent = self.tool_context.agent_username
        previous: datetime | None = self._last_user_timestamp.get(room_id)
        for msg in messages:
            role = "assistant" if msg.username == agent else "user"
            if role == "user":
                ts = format_message_time(msg.timestamp, previous)
                content = f"[{ts}] @{msg.username}: {msg.text}"
                previous = msg.timestamp
            else:
                content = msg.text
            self._conversations[room_id].append(
                MessageParam(role=role, content=content)
            )
        if previous is not None:
            self._last_user_timestamp[room_id] = previous
        return len(messages)

    def has_history(self, room_id: str) -> bool:
        """Check if we have history for a room."""
        return room_id in self._conversations

    async def process(
        self,
        room_id: str,
        content: MessageContent,
        callbacks: ProcessCallbacks | None = None,
        model: str = "",
        thinking: bool = False,
        room_context: str = "",
    ) -> BrainResponse:
        """Process a message and return a response with tool call info."""
        tier = model or CHAT_MODEL

        system = build_system_blocks(self._workspace)

        tools = registry.definitions()
        if tools:
            tools = [*tools]
            tools[-1].cache_control = CacheControl()

        self.tool_context.username = content.username
        self.tool_context.room_id = room_id if not room_id.startswith("__") else ""
        self.tool_context.thread_id = content.thread_id

        async with self._conversation_locks[room_id]:
            if self._room_token_counts.get(room_id, 0) > COMPACT_THRESHOLD:
                await self._compact_history(room_id, system, tools, tier)
                # Reset profiles after compaction since history is cleared
                self._profiles_loaded[room_id].clear()

            messages = self._conversations[room_id]

            # Layer B: Load user profiles on first message from each user in conversation
            current_user = content.username
            if current_user not in self._profiles_loaded[room_id]:
                profile = load_person_context(self._workspace, current_user)
                if profile:
                    profile_message = (
                        f"## What I know about @{current_user}\n\n{profile}"
                    )
                    messages.append(
                        MessageParam(role="system", content=profile_message)
                    )
                    log.info(
                        "→ BRAIN: [profile %s]: %s",
                        current_user,
                        profile[:200] + "..." if len(profile) > 200 else profile,
                    )
                self._profiles_loaded[room_id].add(current_user)

            # Layer C: Per-message context - just timestamp, room/thread, @username: message
            user_content = self._build_content(content, room_id)
            self._conversations[room_id].append(
                MessageParam(role="user", content=user_content)
            )

            messages = self._conversations[room_id]

            log.debug("Processing message with %d history messages", len(messages))

            # Log the user message being sent to the brain (not system prompt)
            last_msg = messages[-1]
            log.info("→ BRAIN: %s", _format_message_for_log(last_msg))

            try:
                reply = await self._backend.run_agentic_loop(
                    tier,
                    system,
                    messages,
                    tools,
                    self.tool_context,
                    self._audit_path,
                    self._usage_path,
                    callbacks,
                    thinking=thinking,
                )
            except ContextTooLargeError:
                log.warning("Request too large, compacting and retrying", exc_info=True)
                await self._compact_history(room_id, system, tools, tier)
                try:
                    reply = await self._backend.run_agentic_loop(
                        tier,
                        system,
                        messages,
                        tools,
                        self.tool_context,
                        self._audit_path,
                        self._usage_path,
                        callbacks,
                        thinking=thinking,
                    )
                except ContextTooLargeError:
                    log.error("Still too large after compaction", exc_info=True)
                    return BrainResponse(text=APOLOGY)
            except BackendAuthError:
                raise
            except BackendError:
                log.error("API error during processing", exc_info=True)
                return BrainResponse(text=APOLOGY)

            if reply:
                self._conversations[room_id].append(
                    MessageParam(role="assistant", content=reply)
                )
                log.info("← BRAIN: %s", reply)

            tokens = await self._measure_context(room_id, system, tools, tier)
            log.info(
                "Context: %d / %d tokens for room %s",
                tokens,
                CONTEXT_BUDGET,
                room_id,
            )

            return BrainResponse(text=reply)

    async def _measure_context(
        self,
        room_id: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        tier: str,
    ) -> int:
        """Count tokens for the current conversation state."""
        count = await self._backend.count_tokens(
            tier, system, tools, self._conversations[room_id]
        )
        if count < 0:
            log.warning(
                "Token counting failed for room %s, using cached value", room_id
            )
            return self._room_token_counts.get(room_id, 0)
        self._room_token_counts[room_id] = count
        return count

    async def _compact_history(
        self,
        room_id: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        tier: str,
    ) -> None:
        old_count = len(self._conversations[room_id])
        await compact_history(self._backend, self._conversations, room_id)
        new_count = len(self._conversations[room_id])
        if new_count < old_count:
            tokens = await self._measure_context(room_id, system, tools, tier)
            log.info(
                "Compacted room %s: %d → %d messages (%d tokens)",
                room_id,
                old_count,
                new_count,
                tokens,
            )

    async def _summarize_webpage(self, text: str, purpose: str) -> str:
        return await summarize_webpage(self._backend, text, purpose)

    async def _classify_response(
        self, url: str, status_code: int, headers: str
    ) -> bool:
        return await classify_response(self._backend, url, status_code, headers)

    def _build_content(
        self,
        content: MessageContent,
        room_id: str = "",
    ) -> list[ContentBlockParam] | str:
        """Build content blocks for Claude."""
        blocks: list[ContentBlockParam] = []

        id_tag = f"[{content.message_id}] " if content.message_id else ""
        ts_tag = ""
        if content.timestamp:
            previous = self._last_user_timestamp.get(room_id)
            ts_tag = f"[{format_message_time(content.timestamp, previous)}] "
            self._last_user_timestamp[room_id] = content.timestamp
        thread_tag = f"[thread:{content.thread_id}] " if content.thread_id else ""
        prefix = f"{id_tag}{ts_tag}{thread_tag}"
        empty = f"{prefix}@{content.username}: (empty message)"

        for media_type, data in content.images:
            blocks.append(
                ImageBlockParam(
                    type="image",
                    source=Base64ImageSourceParam(
                        type="base64",
                        media_type=media_type,
                        data=base64.b64encode(data).decode("utf-8"),
                    ),
                )
            )

        text = f"{prefix}@{content.username}: {content.text}" if content.text else ""

        if text:
            blocks.append(TextBlockParam(type="text", text=text))
        elif not blocks:
            blocks.append(TextBlockParam(type="text", text=empty))

        if len(blocks) == 1 and isinstance(blocks[0], TextBlockParam):
            return blocks[0].text

        return blocks
