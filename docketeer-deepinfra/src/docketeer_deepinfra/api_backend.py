"""DeepInfraAPIBackend: InferenceBackend backed by DeepInfra via OpenAI SDK."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from openai import APIError, AsyncOpenAI, AuthenticationError, RateLimitError

from docketeer import environment
from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
    InferenceBackend,
)
from docketeer.brain.core import InferenceModel
from docketeer_deepinfra import TIER_MAX_TOKENS
from docketeer_deepinfra.loop import _serialize_messages, agentic_loop

if TYPE_CHECKING:
    from docketeer.brain.core import ProcessCallbacks
    from docketeer.prompt import MessageParam, SystemBlock
    from docketeer.tools import ToolContext, ToolDefinition

log = logging.getLogger(__name__)

DEFAULT_MODEL = "MiniMaxAI/MiniMax-M2.5"


class DeepInfraAPIBackend(InferenceBackend):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepinfra.com/v1",
        default_model: str = DEFAULT_MODEL,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key=api_key,
            max_retries=0,
            timeout=300.0,
        )

    async def __aexit__(self, *exc: object) -> None:
        await self._client.close()

    async def run_agentic_loop(
        self,
        tier: str,
        system: list[SystemBlock],
        messages: list[MessageParam],
        tools: list[ToolDefinition],
        tool_context: ToolContext,
        audit_path: Path,
        usage_path: Path,
        callbacks: ProcessCallbacks | None,
        *,
        thinking: bool = False,
    ) -> str:
        # Resolve tier to InferenceModel using environment variables
        model_id = environment.get_str(
            f"DEEPINFRA_MODEL_{tier.upper()}", self._default_model
        )
        max_tokens = TIER_MAX_TOKENS.get(tier, 64_000)
        model = InferenceModel(model_id=model_id, max_output_tokens=max_tokens)

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
                default_model=self._default_model,
            )
        except RateLimitError as exc:
            raise BackendAuthError(str(exc)) from exc
        except AuthenticationError as exc:
            raise BackendAuthError(str(exc)) from exc
        except APIError as exc:
            msg = str(exc).lower()
            if "413" in msg or "payload too large" in msg or "context length" in msg:
                raise ContextTooLargeError(str(exc)) from exc
            raise BackendError(str(exc)) from exc

    async def count_tokens(
        self,
        model_id: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        messages: list[MessageParam],
    ) -> int:
        serialized = _serialize_messages(system, messages)
        return len(json.dumps(serialized)) // 4

    async def utility_complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._default_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except APIError as exc:
            raise BackendError(str(exc)) from exc
