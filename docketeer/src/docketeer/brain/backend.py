"""InferenceBackend ABC: the interface Brain uses to talk to LLMs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docketeer.brain.core import ProcessCallbacks
    from docketeer.prompt import SystemBlock
    from docketeer.tools import ToolContext, ToolDefinition


class BackendError(Exception):
    """Base class for backend errors."""


class ContextTooLargeError(BackendError):
    """The request exceeded the model's context window."""


class BackendAuthError(BackendError):
    """Authentication or permission error from the backend."""


class InferenceBackend(ABC):
    async def __aenter__(self) -> InferenceBackend:
        return self

    async def __aexit__(self, *exc: object) -> None:  # noqa: B027
        pass

    @abstractmethod
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
    ) -> str: ...

    @abstractmethod
    async def count_tokens(
        self,
        model_id: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        messages: list,
    ) -> int:
        """Count tokens for the given context. Returns -1 if unsupported."""
        ...

    @abstractmethod
    async def utility_complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> str:
        """One-shot lightweight completion (haiku-tier)."""
        ...


@dataclass
class Usage:
    """Token usage information from an inference backend."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
