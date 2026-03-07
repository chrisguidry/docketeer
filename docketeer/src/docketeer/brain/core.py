"""Brain: the Claude reasoning loop with tool use."""

from __future__ import annotations

import asyncio
import base64
import json
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
from docketeer.brain.helpers import (
    classify_response,
    format_message_for_log,
    summarize_webpage,
)
from docketeer.chat import RoomMessage
from docketeer.executor import CommandExecutor
from docketeer.plugins import discover_all, discover_one
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
    format_message_time,
)
from docketeer.tools import ToolContext, ToolDefinition, registry
from docketeer.watcher import Watcher, WorkspaceWatcher, _format_workspace_pulse

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class InferenceModel:
    """Represents a model configuration for inference backends."""

    model_id: str
    max_output_tokens: int
    thinking_budget: int | None = None


# Note: Core doesn't define model mappings. Each backend registers its own
# models via environment variables or internal defaults.
CHAT_MODEL = environment.get_str("CHAT_MODEL", "balanced")


CONTEXT_BUDGET = 180_000
COMPACT_THRESHOLD = 140_000

APOLOGY = (
    "I'm sorry, I ran into a temporary problem and couldn't finish processing that. "
    "Could you try again in a moment?"
)


def _create_backend(
    executor: CommandExecutor,
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
    def __init__(
        self,
        tool_context: ToolContext,
        watcher: Watcher | None = None,
    ) -> None:
        self._backend = _create_backend(executor=tool_context.executor)
        self.tool_context = tool_context
        self._workspace = tool_context.workspace
        self._watcher = watcher or WorkspaceWatcher(self._workspace)
        self._audit_path = tool_context.workspace.parent / "audit"
        self._usage_path = tool_context.workspace.parent / "token-usage"
        self._conversations: dict[str, list[MessageParam]] = defaultdict(list)
        self._conversation_locks: defaultdict[str, asyncio.Lock] = defaultdict(
            asyncio.Lock
        )
        self._token_counts: dict[str, int] = {}
        self._last_user_timestamp: dict[str, datetime] = {}
        self._profiles_loaded: dict[str, set[str]] = defaultdict(set)
        self._line_context_loaded: dict[str, bool] = {}
        self._context_providers = [
            factory() for factory in discover_all("docketeer.context")
        ]

        self.tool_context.summarize = self._summarize_webpage
        self.tool_context.classify_response = self._classify_response

    async def __aenter__(self) -> Brain:
        self._stack = AsyncExitStack()
        await self._stack.enter_async_context(self._backend)
        await self._stack.enter_async_context(self._watcher)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    def load_history(self, line: str, messages: list[RoomMessage]) -> int:
        """Load conversation history for a line. Returns count loaded."""
        agent = self.tool_context.agent_username
        previous: datetime | None = self._last_user_timestamp.get(line)
        for msg in messages:
            role = "assistant" if msg.username == agent else "user"
            if role == "user":
                ts = format_message_time(msg.timestamp, previous)
                content = f"[{ts}] @{msg.username}: {msg.text}"
                previous = msg.timestamp
            else:
                content = msg.text
            self._conversations[line].append(MessageParam(role=role, content=content))
        if previous is not None:
            self._last_user_timestamp[line] = previous
        return len(messages)

    def has_history(self, line: str) -> bool:
        """Check if we have history for a line."""
        return line in self._conversations

    async def record_own_message(self, line: str, text: str) -> None:
        """Record a message sent by the agent to a line's conversation history."""
        if line == self.tool_context.line:
            return
        if not self.has_history(line):
            return
        messages = self._conversations[line]
        if (
            messages
            and messages[-1].role == "assistant"
            and messages[-1].content == text
        ):
            return
        messages.append(MessageParam(role="assistant", content=text))

    async def process(
        self,
        line: str,
        content: MessageContent,
        callbacks: ProcessCallbacks | None = None,
        tier: str = "",
        thinking: bool = False,
        room_context: str = "",
        room_slug: str = "",
        chat_room: str = "",
    ) -> BrainResponse:
        """Process a message and return a response with tool call info."""
        tier = tier or CHAT_MODEL

        system = build_system_blocks(self._workspace)

        tools = registry.definitions()
        if tools:
            tools = [*tools]
            tools[-1].cache_control = CacheControl()

        self.tool_context.username = content.username
        self.tool_context.line = line
        self.tool_context.chat_room = chat_room
        self.tool_context.thread_id = content.thread_id
        self.tool_context.message_id = content.message_id

        async with self._conversation_locks[line]:
            if self._token_counts.get(line, 0) > COMPACT_THRESHOLD:
                prev_profiles = set(self._profiles_loaded[line])
                prev_line_loaded = line in self._line_context_loaded

                await self._compact_history(line, system, tools, tier)
                self._profiles_loaded[line].clear()
                self._line_context_loaded.pop(line, None)

                context_msgs = self._reinject_context(
                    line,
                    prev_profiles,
                    prev_line_loaded,
                    room_slug,
                )
                if context_msgs:
                    self._conversations[line][0:0] = context_msgs

            messages = self._conversations[line]

            current_user = content.username
            if current_user not in self._profiles_loaded[line]:
                for provider in self._context_providers:
                    messages.extend(provider.for_user(self._workspace, current_user))
                self._profiles_loaded[line].add(current_user)

            if line not in self._line_context_loaded:
                slug = room_slug or line
                for provider in self._context_providers:
                    messages.extend(provider.for_line(self._workspace, slug))
                self._line_context_loaded[line] = True

            # Workspace pulse: inject changes from other contexts
            changed = self._watcher.drain(line)
            if changed:
                messages.append(
                    MessageParam(
                        role="user",
                        content=_format_workspace_pulse(changed),
                    )
                )

            # Layer C: Per-message context - JSON metadata + @username: message
            user_content = self._build_content(content, line, room_context)
            self._conversations[line].append(
                MessageParam(role="user", content=user_content)
            )

            messages = self._conversations[line]

            log.debug("Processing message with %d history messages", len(messages))

            # Log the user message being sent to the brain (not system prompt)
            last_msg = messages[-1]
            log.info("→ BRAIN: %s", format_message_for_log(last_msg))

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
                await self._compact_history(line, system, tools, tier)
                messages = self._conversations[line]
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
                self._conversations[line].append(
                    MessageParam(role="assistant", content=reply)
                )
                log.info("← BRAIN: %s", reply)

            # Absorb this turn's own tool changes so they don't echo back
            # as a false pulse on the next turn.
            self._watcher.drain(line)

            tokens = await self._measure_context(line, system, tools, tier)
            log.info(
                "Context: %d / %d tokens for line %s",
                tokens,
                CONTEXT_BUDGET,
                line,
            )

            return BrainResponse(text=reply)

    async def _measure_context(
        self,
        line: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        tier: str,
    ) -> int:
        """Count tokens for the current conversation state."""
        count = await self._backend.count_tokens(
            tier, system, tools, self._conversations[line]
        )
        if count < 0:
            log.warning("Token counting failed for line %s, using cached value", line)
            return self._token_counts.get(line, 0)
        self._token_counts[line] = count
        return count

    async def _compact_history(
        self,
        line: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        tier: str,
    ) -> None:
        old_count = len(self._conversations[line])
        await compact_history(self._backend, self._conversations, line)
        new_count = len(self._conversations[line])
        if new_count < old_count:
            tokens = await self._measure_context(line, system, tools, tier)
            log.info(
                "Compacted line %s: %d → %d messages (%d tokens)",
                line,
                old_count,
                new_count,
                tokens,
            )

    def _reinject_context(
        self,
        line: str,
        prev_profiles: set[str],
        prev_line_loaded: bool,
        room_slug: str,
    ) -> list[MessageParam]:
        """Re-read profile/line context after compaction for prepending."""
        msgs: list[MessageParam] = []
        for username in sorted(prev_profiles):
            for provider in self._context_providers:
                user_msgs = provider.for_user(self._workspace, username)
                msgs.extend(
                    m for m in user_msgs if "don't have a profile" not in m.content
                )
            self._profiles_loaded[line].add(username)
        if prev_line_loaded:
            slug = room_slug or line
            for provider in self._context_providers:
                msgs.extend(provider.for_line(self._workspace, slug))
            self._line_context_loaded[line] = True
        return msgs

    async def _summarize_webpage(self, text: str, purpose: str) -> str:
        return await summarize_webpage(self._backend, text, purpose)

    async def _classify_response(
        self, url: str, status_code: int, headers: str
    ) -> bool:
        return await classify_response(self._backend, url, status_code, headers)

    def _build_content(
        self,
        content: MessageContent,
        line: str = "",
        room_context: str = "",
    ) -> list[ContentBlockParam] | str:
        """Build content blocks for Claude."""
        blocks: list[ContentBlockParam] = []

        # JSON metadata line
        meta: dict[str, str] = {
            "now": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if room_context:
            meta["room"] = room_context
        if content.message_id:
            meta["message_id"] = content.message_id
        if content.thread_id:
            meta["thread"] = content.thread_id

        # Track delta timestamps for history formatting
        if content.timestamp:
            previous = self._last_user_timestamp.get(line)
            meta["delta"] = format_message_time(content.timestamp, previous)
            self._last_user_timestamp[line] = content.timestamp

        meta_line = json.dumps(meta)
        message_line = (
            f"@{content.username}: {content.text}"
            if content.text
            else f"@{content.username}: (empty message)"
        )

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

        if blocks:
            # Image messages: JSON line as a separate text block before images
            blocks.insert(
                0,
                TextBlockParam(type="text", text=f"{meta_line}\n{message_line}"),
            )
            return blocks

        return f"{meta_line}\n{message_line}"
