"""Brain: the Claude reasoning loop with tool use."""

import base64
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import anthropic
from anthropic import APIError, AuthenticationError, PermissionDeniedError
from anthropic._exceptions import RequestTooLargeError
from anthropic.types import (
    Base64ImageSourceParam,
    ContentBlockParam,
    ImageBlockParam,
    MessageParam,
    TextBlockParam,
)

from docketeer import environment
from docketeer.brain.compaction import compact_history
from docketeer.brain.helpers import classify_response, summarize_webpage
from docketeer.brain.loop import agentic_loop
from docketeer.chat import RoomMessage
from docketeer.people import build_person_map, load_person_context
from docketeer.prompt import (
    BrainResponse,
    CacheControl,
    MessageContent,
    RoomInfo,
    SystemBlock,
    build_system_blocks,
    ensure_template,
)
from docketeer.tools import ToolContext, ToolDefinition, registry

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = environment.get_str("ANTHROPIC_API_KEY")
CLAUDE_MODEL = environment.get_str("CLAUDE_MODEL", "claude-opus-4-6")

CONTEXT_BUDGET = 180_000
COMPACT_THRESHOLD = 140_000

APOLOGY = (
    "I'm sorry, I ran into a temporary problem and couldn't finish processing that. "
    "Could you try again in a moment?"
)


@dataclass
class ProcessCallbacks:
    """Optional callbacks fired during process() for typing/presence signals."""

    on_first_text: Callable[[], Awaitable[None]] | None = None
    on_tool_start: Callable[[], Awaitable[None]] | None = None
    on_tool_end: Callable[[], Awaitable[None]] | None = None


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

        tools = registry.definitions()
        if tools:
            tools = [*tools]
            tools[-1].cache_control = CacheControl()

        self.tool_context.username = content.username
        self.tool_context.room_id = room_id

        if self._room_token_counts.get(room_id, 0) > COMPACT_THRESHOLD:
            await self._compact_history(room_id, system, tools)

        user_content = self._build_content(content)
        self._conversations[room_id].append(
            MessageParam(role="user", content=user_content)
        )

        messages = self._conversations[room_id]

        log.debug("Processing message with %d history messages", len(messages))

        try:
            reply = await agentic_loop(
                self.client,
                system,
                messages,
                tools,
                self.tool_context,
                self._audit_path,
                callbacks.on_first_text if callbacks else None,
                callbacks.on_tool_start if callbacks else None,
                callbacks.on_tool_end if callbacks else None,
            )
        except RequestTooLargeError:
            log.warning("Request too large, compacting and retrying", exc_info=True)
            await self._compact_history(room_id, system, tools)
            try:
                reply = await agentic_loop(
                    self.client,
                    system,
                    messages,
                    tools,
                    self.tool_context,
                    self._audit_path,
                    callbacks.on_first_text if callbacks else None,
                    callbacks.on_tool_start if callbacks else None,
                    callbacks.on_tool_end if callbacks else None,
                )
            except RequestTooLargeError:
                log.error("Still too large after compaction", exc_info=True)
                return BrainResponse(text=APOLOGY)
        except (AuthenticationError, PermissionDeniedError):
            raise
        except APIError:
            log.error("API error during processing", exc_info=True)
            return BrainResponse(text=APOLOGY)

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

    async def _measure_context(
        self, room_id: str, system: list[SystemBlock], tools: list[ToolDefinition]
    ) -> int:
        """Count tokens for the current conversation state."""
        try:
            result = await self.client.messages.count_tokens(
                model=CLAUDE_MODEL,
                system=[b.to_api_dict() for b in system],
                tools=[t.to_api_dict() for t in tools],
                messages=self._conversations[room_id],
            )
        except APIError:
            log.warning("Token counting failed, using stale count", exc_info=True)
            return self._room_token_counts.get(room_id, 0)
        self._room_token_counts[room_id] = result.input_tokens
        return result.input_tokens

    async def _compact_history(
        self, room_id: str, system: list[SystemBlock], tools: list[ToolDefinition]
    ) -> None:
        old_count = len(self._conversations[room_id])
        await compact_history(self.client, self._conversations, room_id)
        new_count = len(self._conversations[room_id])
        if new_count < old_count:
            tokens = await self._measure_context(room_id, system, tools)
            log.info(
                "Compacted room %s: %d → %d messages (%d tokens)",
                room_id,
                old_count,
                new_count,
                tokens,
            )

    async def _summarize_webpage(self, text: str, purpose: str) -> str:
        return await summarize_webpage(self.client, text, purpose)

    async def _classify_response(
        self, url: str, status_code: int, headers: str
    ) -> bool:
        return await classify_response(self.client, url, status_code, headers)

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
