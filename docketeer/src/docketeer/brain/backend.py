"""InferenceBackend ABC: the interface Brain uses to talk to LLMs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docketeer.brain.core import InferenceModel, ProcessCallbacks
    from docketeer.prompt import SystemBlock
    from docketeer.tools import ToolContext, ToolDefinition


class BackendError(Exception):
    """Base class for backend errors."""


class ContextTooLargeError(BackendError):
    """The request exceeded the model's context window."""


class BackendAuthError(BackendError):
    """Authentication or permission error from the backend."""


class InferenceBackend(ABC):
    @abstractmethod
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
