"""Tests for stream_message in the agentic loop."""

from unittest.mock import AsyncMock, MagicMock

from docketeer.brain.core import InferenceModel
from docketeer.prompt import MessageParam, SystemBlock
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


async def test_basic_content_accumulation():
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = "Hello "
    chunk1.choices[0].delta.tool_calls = None
    chunk1.choices[0].finish_reason = None
    chunk1.usage = None

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = "world"
    chunk2.choices[0].delta.tool_calls = None
    chunk2.choices[0].finish_reason = "stop"
    chunk2.usage = None

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk1, chunk2])

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[SystemBlock(text="You are helpful.")],
        messages=[MessageParam(role="user", content="hi")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.choices[0].message.content == "Hello world"
    assert result.choices[0].finish_reason == "stop"


async def test_tool_calls_accumulated_across_chunks():
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta = MagicMock()
    chunk1.choices[0].delta.content = None
    tc1 = MagicMock()
    tc1.index = 0
    tc1.id = "call_abc"
    tc1.function = MagicMock()
    tc1.function.name = "list"
    tc1.function.arguments = '{"path":'
    chunk1.choices[0].delta.tool_calls = [tc1]
    chunk1.choices[0].finish_reason = None
    chunk1.usage = None

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta = MagicMock()
    chunk2.choices[0].delta.content = None
    tc2 = MagicMock()
    tc2.index = 0
    tc2.id = None
    tc2.function = MagicMock()
    tc2.function.name = ""
    tc2.function.arguments = ' "/"}'
    chunk2.choices[0].delta.tool_calls = [tc2]
    chunk2.choices[0].finish_reason = "tool_calls"
    chunk2.usage = None

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk1, chunk2])

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )

    tc = result.choices[0].message.tool_calls
    assert tc is not None
    assert len(tc) == 1
    assert tc[0].id == "call_abc"
    assert tc[0].function.name == "list"  # type: ignore[possibly-missing-attribute]
    assert tc[0].function.arguments == '{"path": "/"}'  # type: ignore[possibly-missing-attribute]


async def test_multiple_tool_calls_in_one_chunk():
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = None
    chunk.usage = None

    tc1 = MagicMock()
    tc1.index = 0
    tc1.id = "call_1"
    tc1.function = MagicMock()
    tc1.function.name = "tool_a"
    tc1.function.arguments = '{"a": 1}'

    tc2 = MagicMock()
    tc2.index = 1
    tc2.id = "call_2"
    tc2.function = MagicMock()
    tc2.function.name = "tool_b"
    tc2.function.arguments = '{"b": 2}'

    chunk.choices[0].delta.tool_calls = [tc1, tc2]
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

    tc = result.choices[0].message.tool_calls
    assert tc is not None
    assert len(tc) == 2
    assert tc[0].id == "call_1"
    assert tc[0].function.name == "tool_a"  # type: ignore[possibly-missing-attribute]
    assert tc[1].id == "call_2"
    assert tc[1].function.name == "tool_b"  # type: ignore[possibly-missing-attribute]


async def test_on_first_text_callback_fires_once():
    calls: list[bool] = []

    async def on_first_text() -> None:
        calls.append(True)

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

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk1, chunk2])

    await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=on_first_text,
        default_model="test-model",
    )

    assert calls == [True]


async def test_empty_choices_skipped():
    empty_chunk = MagicMock()
    empty_chunk.choices = []
    empty_chunk.usage = None

    real_chunk = MagicMock()
    real_chunk.choices = [MagicMock()]
    real_chunk.choices[0].delta = MagicMock()
    real_chunk.choices[0].delta.content = "Hello"
    real_chunk.choices[0].delta.tool_calls = None
    real_chunk.choices[0].finish_reason = "stop"
    real_chunk.usage = None

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([empty_chunk, real_chunk])

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.choices[0].message.content == "Hello"


async def test_none_delta_skipped():
    no_delta = MagicMock()
    no_delta.choices = [MagicMock()]
    no_delta.choices[0].delta = None
    no_delta.usage = None

    real_chunk = MagicMock()
    real_chunk.choices = [MagicMock()]
    real_chunk.choices[0].delta = MagicMock()
    real_chunk.choices[0].delta.content = "Hello"
    real_chunk.choices[0].delta.tool_calls = None
    real_chunk.choices[0].finish_reason = "stop"
    real_chunk.usage = None

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([no_delta, real_chunk])

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.choices[0].message.content == "Hello"


async def test_empty_tool_arguments_default_to_empty_object():
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = None
    chunk.usage = None
    tc = MagicMock()
    tc.index = 0
    tc.id = "call_123"
    tc.function = MagicMock()
    tc.function.name = "no_args"
    tc.function.arguments = ""
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
    assert result.choices[0].message.tool_calls[0].function.arguments == "{}"  # type: ignore[index, union-attr]


async def test_invalid_json_arguments_default_to_empty_object():
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = None
    chunk.usage = None
    tc = MagicMock()
    tc.index = 0
    tc.id = "call_123"
    tc.function = MagicMock()
    tc.function.name = "bad_json"
    tc.function.arguments = "not valid json{"
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
    assert result.choices[0].message.tool_calls[0].function.arguments == "{}"  # type: ignore[index, union-attr]


async def test_tools_passed_to_api():
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = "Hello"
    chunk.choices[0].delta.tool_calls = None
    chunk.choices[0].finish_reason = "stop"
    chunk.usage = None

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk])

    mock_tool = MagicMock()
    mock_tool.to_api_dict.return_value = {
        "type": "function",
        "function": {"name": "test_tool", "parameters": {}},
    }

    await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[mock_tool],
        on_first_text=None,
        default_model="test-model",
    )

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tools"] is not None
    assert len(call_kwargs["tools"]) == 1


async def test_model_id_fallback_to_default():
    model_empty = InferenceModel(model_id="", max_output_tokens=64_000)

    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = "Hello"
    chunk.choices[0].delta.tool_calls = None
    chunk.choices[0].finish_reason = "stop"
    chunk.usage = None

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk])

    await stream_message(
        client=mock_client,
        model=model_empty,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="fallback-model",
    )

    assert (
        mock_client.chat.completions.create.call_args.kwargs["model"]
        == "fallback-model"
    )
