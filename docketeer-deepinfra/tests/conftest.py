"""Shared test fixtures and helpers for docketeer-deepinfra tests."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai.types import CompletionUsage
from openai.types.completion_usage import PromptTokensDetails

from docketeer.brain.core import InferenceModel
from docketeer.tools import ToolContext

MODEL = InferenceModel(
    model_id="meta-llama/Llama-3.3-70B-Instruct", max_output_tokens=64_000
)


@pytest.fixture()
def mock_client() -> MagicMock:
    """An OpenAI client mock with chat.completions.create pre-wired."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path, username="test-user")


class AsyncStreamWrapper:
    def __init__(self, chunks: list[MagicMock]) -> None:
        self.chunks = list(chunks)
        self._index = 0

    def __aiter__(self) -> "AsyncStreamWrapper":
        return self

    async def __anext__(self) -> MagicMock:
        if self._index >= len(self.chunks):
            raise StopAsyncIteration
        chunk = self.chunks[self._index]
        self._index += 1
        return chunk


def make_stream_mock(chunks: list[MagicMock]) -> AsyncMock:
    return AsyncMock(return_value=AsyncStreamWrapper(chunks))


def make_chunk(
    content: str | None = None,
    finish_reason: str | None = None,
    tool_calls: list[MagicMock] | None = None,
    usage: CompletionUsage | None = None,
) -> MagicMock:
    """Build a single streaming chunk."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = content
    chunk.choices[0].delta.tool_calls = tool_calls
    chunk.choices[0].finish_reason = finish_reason
    chunk.usage = usage
    return chunk


def make_tool_call(
    index: int = 0,
    call_id: str | None = "call_1",
    name: str = "test_tool",
    arguments: str = "{}",
) -> MagicMock:
    """Build a tool call delta for a streaming chunk."""
    tc = MagicMock()
    tc.index = index
    tc.id = call_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def make_usage(
    prompt_tokens: int = 100,
    completion_tokens: int = 10,
    total_tokens: int = 110,
    cached_tokens: int | None = None,
) -> CompletionUsage:
    """Build a CompletionUsage, optionally with cached token details."""
    kwargs: dict[str, object] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    if cached_tokens is not None:
        kwargs["prompt_tokens_details"] = PromptTokensDetails(
            cached_tokens=cached_tokens
        )
    return CompletionUsage(**kwargs)  # type: ignore[arg-type]


def make_response(
    content: str | None = None,
    finish_reason: str = "stop",
    tool_calls: list[MagicMock] | None = None,
    usage: MagicMock | None = None,
) -> MagicMock:
    """Build a complete (non-streaming) chat completion response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage or MagicMock(prompt_tokens=10, completion_tokens=5)
    return resp
