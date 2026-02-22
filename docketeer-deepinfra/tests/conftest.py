"""Shared test fixtures and helpers for docketeer-deepinfra tests."""

from unittest.mock import AsyncMock, MagicMock

from openai.types import CompletionUsage

from docketeer.brain.core import InferenceModel

MODEL = InferenceModel(
    model_id="meta-llama/Llama-3.3-70B-Instruct", max_output_tokens=64_000
)


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
