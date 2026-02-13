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

from anthropic.types import (
    Base64ImageSourceParam,
    ContentBlockParam,
    ImageBlockParam,
    MessageParam,
    TextBlockParam,
)

from docketeer import environment
from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
    InferenceBackend,
)
from docketeer.brain.compaction import compact_history
from docketeer.brain.helpers import classify_response, summarize_webpage
from docketeer.chat import RoomInfo, RoomMessage
from docketeer.executor import CommandExecutor
from docketeer.people import build_person_map, load_person_context
from docketeer.prompt import (
    BrainResponse,
    CacheControl,
    MessageContent,
    SystemBlock,
    build_dynamic_context,
    build_system_blocks,
    ensure_template,
)
from docketeer.tools import ToolContext, ToolDefinition, registry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class InferenceModel:
    model_id: str
    max_output_tokens: int
    thinking_budget: int | None = None


MODELS: dict[str, InferenceModel] = {
    "opus": InferenceModel(
        model_id=environment.get_str("MODEL_OPUS", "claude-opus-4-6"),
        max_output_tokens=128_000,
    ),
    "sonnet": InferenceModel(
        model_id=environment.get_str("MODEL_SONNET", "claude-sonnet-4-5-20250929"),
        max_output_tokens=64_000,
        thinking_budget=10_000,
    ),
    "haiku": InferenceModel(
        model_id=environment.get_str("MODEL_HAIKU", "claude-haiku-4-5-20251001"),
        max_output_tokens=16_000,
    ),
}

CHAT_MODEL = environment.get_str("CHAT_MODEL", "opus")
REVERIE_MODEL = environment.get_str("REVERIE_MODEL", "opus")
CONSOLIDATION_MODEL = environment.get_str("CONSOLIDATION_MODEL", "opus")


def resolve_model(tier: str) -> InferenceModel:
    """Resolve a tier name like 'opus' to its InferenceModel."""
    return MODELS[tier]


CONTEXT_BUDGET = 180_000
COMPACT_THRESHOLD = 140_000

APOLOGY = (
    "I'm sorry, I ran into a temporary problem and couldn't finish processing that. "
    "Could you try again in a moment?"
)


def _create_backend(
    executor: CommandExecutor | None = None,
) -> InferenceBackend:
    """Create the inference backend based on DOCKETEER_INFERENCE env var."""
    mode = environment.get_str("INFERENCE", "api")
    if mode == "api":
        from docketeer.brain.anthropic_backend import AnthropicAPIBackend

        api_key = environment.get_str("ANTHROPIC_API_KEY")
        return AnthropicAPIBackend(api_key)
    if mode == "claude-code":
        from docketeer.brain.claude_code_backend import ClaudeCodeBackend

        if executor is None:
            raise ValueError("claude-code backend requires an executor plugin")
        oauth_token = environment.get_str("CLAUDE_CODE_OAUTH_TOKEN")
        return ClaudeCodeBackend(executor=executor, oauth_token=oauth_token)
    raise ValueError(f"Unknown inference backend: {mode!r}")


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
        self._room_token_counts: dict[str, int] = {}
        self._room_info: dict[str, RoomInfo] = {}
        self._person_map: dict[str, str] = {}

        soul_path = self._workspace / "SOUL.md"
        first_run = not soul_path.exists()
        ensure_template(self._workspace, "soul.md")
        if first_run:
            ensure_template(self._workspace, "bootstrap.md")

        ensure_template(self._workspace, "practice.md")

        self.tool_context.summarize = self._summarize_webpage
        self.tool_context.classify_response = self._classify_response

        self._person_map = build_person_map(self._workspace)
        log.info("Person map: %s", self._person_map)

    async def __aenter__(self) -> Brain:
        self._stack = AsyncExitStack()
        await self._stack.enter_async_context(self._backend)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    def set_room_info(self, room_id: str, info: RoomInfo) -> None:
        """Store metadata about a room for use in the system prompt."""
        self._room_info[room_id] = info

    def rebuild_person_map(self) -> None:
        """Rebuild the username->person-file mapping after a people/ write."""
        self._person_map = build_person_map(self._workspace)
        log.info("Rebuilt person map: %s", self._person_map)

    def load_history(self, room_id: str, messages: list[RoomMessage]) -> int:
        """Load conversation history for a room. Returns count loaded."""
        agent = self.tool_context.agent_username
        for msg in messages:
            role = "assistant" if msg.username == agent else "user"
            if role == "user":
                ts = msg.timestamp.astimezone().strftime("%Y-%m-%d %H:%M")
                content = f"[{ts}] @{msg.username}: {msg.text}"
            else:
                content = msg.text
            self._conversations[room_id].append(
                MessageParam(role=role, content=content)
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
        model: str = "",
        thinking: bool = False,
    ) -> BrainResponse:
        """Process a message and return a response with tool call info."""
        model = model or CHAT_MODEL
        resolved = resolve_model(model)

        current_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
        person_context = load_person_context(
            self._workspace,
            content.username,
            self._person_map,
        )
        room_info = self._room_info.get(room_id)
        system = build_system_blocks(self._workspace)
        dynamic_context = build_dynamic_context(
            current_time,
            content.username,
            person_context=person_context,
            room_info=room_info,
        )

        tools = registry.definitions()
        if tools:
            tools = [*tools]
            tools[-1].cache_control = CacheControl()

        self.tool_context.username = content.username
        self.tool_context.room_id = room_id if not room_id.startswith("__") else ""
        self.tool_context.thread_id = content.thread_id

        if self._room_token_counts.get(room_id, 0) > COMPACT_THRESHOLD:
            await self._compact_history(room_id, system, tools, resolved.model_id)

        user_content = self._build_content(content, dynamic_context)
        self._conversations[room_id].append(
            MessageParam(role="user", content=user_content)
        )

        messages = self._conversations[room_id]

        log.debug("Processing message with %d history messages", len(messages))

        try:
            reply = await self._backend.run_agentic_loop(
                resolved,
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
            await self._compact_history(room_id, system, tools, resolved.model_id)
            try:
                reply = await self._backend.run_agentic_loop(
                    resolved,
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

        tokens = await self._measure_context(room_id, system, tools, resolved.model_id)
        log.info(
            "Context: %d / %d tokens for room %s",
            tokens,
            CONTEXT_BUDGET,
            room_id,
        )

        log.debug("Response: %s", reply[:100])
        return BrainResponse(text=reply)

    async def _measure_context(
        self,
        room_id: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        model_id: str,
    ) -> int:
        """Count tokens for the current conversation state."""
        count = await self._backend.count_tokens(
            model_id, system, tools, self._conversations[room_id]
        )
        if count < 0:
            return self._room_token_counts.get(room_id, 0)
        self._room_token_counts[room_id] = count
        return count

    async def _compact_history(
        self,
        room_id: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        model_id: str,
    ) -> None:
        old_count = len(self._conversations[room_id])
        await compact_history(self._backend, self._conversations, room_id)
        new_count = len(self._conversations[room_id])
        if new_count < old_count:
            tokens = await self._measure_context(room_id, system, tools, model_id)
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
        self, content: MessageContent, dynamic_context: str = ""
    ) -> list[ContentBlockParam] | str:
        """Build content blocks for Claude."""
        blocks: list[ContentBlockParam] = []

        if dynamic_context:
            blocks.append(TextBlockParam(type="text", text=dynamic_context))

        id_tag = f"[{content.message_id}] " if content.message_id else ""
        ts_tag = f"[{content.timestamp}] " if content.timestamp else ""
        thread_tag = f"[thread:{content.thread_id}] " if content.thread_id else ""
        prefix = f"{id_tag}{ts_tag}{thread_tag}"
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
            return blocks[0]["text"]

        return blocks
