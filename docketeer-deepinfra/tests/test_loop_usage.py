"""Tests for usage tracking in the agentic loop."""

from unittest.mock import AsyncMock, MagicMock

from docketeer.brain.core import InferenceModel
from docketeer.prompt import MessageParam
from docketeer_deepinfra.loop import stream_message

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


async def test_stream_captures_usage_from_final_chunk():
    """Test that usage from the final chunk is captured."""
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = "Hello"
    chunk1.choices[0].delta.tool_calls = None
    chunk1.choices[0].finish_reason = None
    chunk1.usage = None

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = " world"
    chunk2.choices[0].delta.tool_calls = None
    chunk2.choices[0].finish_reason = "stop"
    chunk2.usage = None

    # Final chunk with usage and empty choices
    from openai.types import CompletionUsage

    usage_chunk = MagicMock()
    usage_chunk.choices = []
    usage_chunk.usage = CompletionUsage(
        prompt_tokens=42, completion_tokens=7, total_tokens=49
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock(
        [chunk1, chunk2, usage_chunk]
    )

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.choices[0].message.content == "Hello world"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 42
    assert result.usage.completion_tokens == 7
    assert result.usage.total_tokens == 49


async def test_stream_captures_cached_tokens():
    """Test that cached_tokens are captured from prompt_tokens_details."""
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = "Hi"
    chunk1.choices[0].delta.tool_calls = None
    chunk1.choices[0].finish_reason = "stop"
    chunk1.usage = None

    # Final chunk with usage including cached_tokens
    from openai.types import CompletionUsage
    from openai.types.completion_usage import PromptTokensDetails

    usage_chunk = MagicMock()
    usage_chunk.choices = []
    usage_chunk.usage = CompletionUsage(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        prompt_tokens_details=PromptTokensDetails(cached_tokens=80),
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk1, usage_chunk])

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.usage is not None
    assert result.usage.prompt_tokens == 100
    assert result.usage.prompt_tokens_details is not None
    assert result.usage.prompt_tokens_details.cached_tokens == 80


async def test_stream_falls_back_to_zero_usage_without_usage_chunk():
    """Test fallback when no usage chunk is present."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = "test"
    chunk.choices[0].delta.tool_calls = None
    chunk.choices[0].finish_reason = "stop"
    chunk.usage = None

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk])

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.usage is not None
    assert result.usage.prompt_tokens == 0
    assert result.usage.completion_tokens == 0


async def test_tool_call_with_none_index_skipped():
    """Test that tool calls with None index are skipped."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = None
    chunk.usage = None
    tc = MagicMock()
    tc.index = None
    tc.id = "call_123"
    tc.function = MagicMock()
    tc.function.name = "test"
    tc.function.arguments = "{}"
    chunk.choices[0].delta.tool_calls = [tc]
    chunk.choices[0].finish_reason = "tool_calls"

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk])

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.choices[0].message.tool_calls is None
