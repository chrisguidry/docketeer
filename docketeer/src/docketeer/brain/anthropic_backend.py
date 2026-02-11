"""AnthropicAPIBackend: InferenceBackend backed by the Anthropic SDK."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
from anthropic import APIError, AuthenticationError, PermissionDeniedError
from anthropic._exceptions import RequestTooLargeError
from anthropic.types import MessageParam, TextBlock

from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
    InferenceBackend,
)
from docketeer.brain.loop import agentic_loop

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
        model: InferenceModel,
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
            result = await self._client.messages.count_tokens(
                model=model_id,
                system=[b.to_api_dict() for b in system],
                tools=[t.to_api_dict() for t in tools],
                messages=messages,
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
        from docketeer.brain.core import MODELS

        try:
            response = await self._client.messages.create(
                model=MODELS["haiku"].model_id,
                max_tokens=max_tokens,
                messages=[MessageParam(role="user", content=prompt)],
            )
        except APIError as exc:
            raise BackendError(str(exc)) from exc
        block = response.content[0]
        return block.text if isinstance(block, TextBlock) else str(block)
