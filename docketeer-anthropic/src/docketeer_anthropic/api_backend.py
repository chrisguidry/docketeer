"""AnthropicAPIBackend: InferenceBackend backed by the Anthropic SDK."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
from anthropic import APIError, AuthenticationError, PermissionDeniedError
from anthropic._exceptions import RequestTooLargeError
from anthropic.types import TextBlock

from docketeer import environment
from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
    InferenceBackend,
)
from docketeer.brain.core import InferenceModel
from docketeer_anthropic import TIER_MAX_TOKENS
from docketeer_anthropic.loop import agentic_loop

if TYPE_CHECKING:
    from docketeer.brain.core import InferenceModel, ProcessCallbacks
    from docketeer.prompt import SystemBlock
    from docketeer.tools import ToolContext, ToolDefinition

log = logging.getLogger(__name__)


class AnthropicAPIBackend(InferenceBackend):
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def run_agentic_loop(
        self,
        tier: str,
        system: list[SystemBlock],
        messages: list,
        tools: list[ToolDefinition],
        tool_context: ToolContext,
        audit_path: Path,
        usage_path: Path,
        callbacks: ProcessCallbacks | None,
        *,
        thinking: bool = False,
    ) -> str:
        # Map tier to Anthropic model
        model_map = {
            "smart": environment.get_str("MODEL_OPUS", "claude-opus-4-6"),
            "balanced": environment.get_str("MODEL_SONNET", "claude-sonnet-4-6"),
            "fast": environment.get_str("MODEL_HAIKU", "claude-haiku-4-5-20251001"),
        }
        model_id = model_map.get(tier, "claude-sonnet-4-6")
        max_tokens = TIER_MAX_TOKENS.get(tier, 64_000)
        thinking_budget = 10_000 if tier == "balanced" else None
        model = InferenceModel(
            model_id=model_id,
            max_output_tokens=max_tokens,
            thinking_budget=thinking_budget,
        )

        try:
            return await agentic_loop(
                self._client,
                model,
                system,
                messages,
                tools,
                tool_context,
                audit_path,
                usage_path,
                callbacks.on_first_text if callbacks else None,
                callbacks.on_text if callbacks else None,
                callbacks.on_tool_start if callbacks else None,
                callbacks.on_tool_end if callbacks else None,
                callbacks.interrupted if callbacks else None,
                thinking=thinking,
            )
        except RequestTooLargeError as exc:
            raise ContextTooLargeError(str(exc)) from exc
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise BackendAuthError(str(exc)) from exc
        except APIError as exc:
            raise BackendError(str(exc)) from exc

    async def count_tokens(
        self,
        model_id: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        messages: list,
    ) -> int:
        try:
            serialized_messages = [
                msg.to_dict() if hasattr(msg, "to_dict") else msg for msg in messages
            ]
            result = await self._client.messages.count_tokens(
                model=model_id,
                system=[self._system_to_dict(b) for b in system],  # type: ignore[arg-type]
                tools=[self._tool_to_dict(t) for t in tools],  # type: ignore[arg-type]
                messages=serialized_messages,
            )
        except APIError:
            log.warning("Token counting failed", exc_info=True)
            return -1
        return result.input_tokens

    async def utility_complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> str:
        from docketeer.prompt import MessageParam as DocketeerMessageParam

        try:
            response = await self._client.messages.create(
                model=environment.get_str("MODEL_HAIKU", "claude-haiku-4-5-20251001"),
                max_tokens=max_tokens,
                messages=[DocketeerMessageParam(role="user", content=prompt).to_dict()],  # type: ignore[arg-type]
            )
        except APIError as exc:
            raise BackendError(str(exc)) from exc
        block = response.content[0]
        return block.text if isinstance(block, TextBlock) else str(block)

    def _system_to_dict(self, block: SystemBlock) -> dict:
        """Convert SystemBlock to dict format."""
        d = {"type": "text", "text": block.text}
        if block.cache_control:
            d["cache_control"] = {"type": "ephemeral", "ttl": block.cache_control.ttl}
        return d

    def _tool_to_dict(self, tool: ToolDefinition) -> dict:
        """Convert ToolDefinition to dict format."""
        try:
            return tool.to_api_dict()  # type: ignore[union-attr]
        except AttributeError:
            return {"name": tool.name, "input_schema": tool.input_schema}
