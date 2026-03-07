"""Shared test constants, classes, and builder functions for docketeer-deepinfra."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import (
    Choice,
    ChoiceDelta,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)
from openai.types.completion_usage import PromptTokensDetails

from docketeer.brain.core import InferenceModel

MODEL = InferenceModel(
    model_id="meta-llama/Llama-3.3-70B-Instruct", max_output_tokens=64_000
)


class FakeAsyncStream:
    """Async iterable of ChatCompletionChunk objects, mimicking AsyncStream."""

    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> FakeAsyncStream:
        return self

    async def __anext__(self) -> ChatCompletionChunk:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def make_chunks(
    content: str | None = None,
    finish_reason: str = "stop",
    tool_calls: list[ChoiceDeltaToolCall] | None = None,
    usage: CompletionUsage | None = None,
) -> FakeAsyncStream:
    """Build a stream of chunks that ChatCompletionStreamState can accumulate."""
    chunks: list[ChatCompletionChunk] = []

    # Initial content or tool call chunk
    delta_kwargs: dict[str, Any] = {"role": "assistant"}
    if content is not None:
        delta_kwargs["content"] = content
    if tool_calls:
        delta_kwargs["tool_calls"] = tool_calls

    chunks.append(
        ChatCompletionChunk(
            id="chatcmpl-test",
            choices=[
                Choice(index=0, delta=ChoiceDelta(**delta_kwargs), finish_reason=None)
            ],
            created=0,
            model="test-model",
            object="chat.completion.chunk",
        )
    )

    # Finish chunk
    chunks.append(
        ChatCompletionChunk(
            id="chatcmpl-test",
            choices=[Choice(index=0, delta=ChoiceDelta(), finish_reason=finish_reason)],  # type: ignore[arg-type]
            created=0,
            model="test-model",
            object="chat.completion.chunk",
        )
    )

    # Usage chunk
    chunks.append(
        ChatCompletionChunk(
            id="chatcmpl-test",
            choices=[],
            created=0,
            model="test-model",
            object="chat.completion.chunk",
            usage=usage
            or CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
    )

    return FakeAsyncStream(chunks)


def make_tc_delta(
    index: int = 0,
    call_id: str = "call_1",
    name: str = "test_tool",
    arguments: str = "{}",
) -> ChoiceDeltaToolCall:
    """Build a tool call delta for a streaming chunk."""
    return ChoiceDeltaToolCall(
        index=index,
        id=call_id,
        type="function",
        function=ChoiceDeltaToolCallFunction(name=name, arguments=arguments),
    )


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


def make_tool_call(
    index: int = 0,
    call_id: str | None = "call_1",
    name: str = "test_tool",
    arguments: str = "{}",
) -> MagicMock:
    """Build a mock tool call for tests that patch stream_message."""
    tc = MagicMock()
    tc.index = index
    tc.id = call_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def make_response(
    content: str | None = None,
    finish_reason: str = "stop",
    tool_calls: list[MagicMock] | None = None,
    usage: MagicMock | None = None,
) -> MagicMock:
    """Build a mock response for tests that patch stream_message."""
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
