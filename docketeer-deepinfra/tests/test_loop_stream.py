"""Tests for stream_message in the agentic loop."""

from unittest.mock import MagicMock

from docketeer.brain.core import InferenceModel
from docketeer.prompt import MessageParam, SystemBlock
from docketeer.tools import ToolDefinition
from docketeer_deepinfra.loop import stream_message

from .conftest import MODEL, make_chunk, make_stream_mock, make_tool_call


async def test_basic_content_accumulation(mock_client: MagicMock):
    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(content="Hello "),
            make_chunk(content="world", finish_reason="stop"),
        ]
    )

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


async def test_tool_calls_accumulated_across_chunks(mock_client: MagicMock):
    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(
                tool_calls=[
                    make_tool_call(
                        index=0,
                        call_id="call_abc",
                        name="list",
                        arguments='{"path":',
                    )
                ],
            ),
            make_chunk(
                tool_calls=[
                    make_tool_call(
                        index=0,
                        call_id=None,
                        name="",
                        arguments=' "/"}',
                    )
                ],
                finish_reason="tool_calls",
            ),
        ]
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

    tc = result.choices[0].message.tool_calls
    assert tc is not None
    assert len(tc) == 1
    assert tc[0].id == "call_abc"
    assert tc[0].function.name == "list"  # type: ignore[possibly-missing-attribute]
    assert tc[0].function.arguments == '{"path": "/"}'  # type: ignore[possibly-missing-attribute]


async def test_multiple_tool_calls_in_one_chunk(mock_client: MagicMock):
    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(
                tool_calls=[
                    make_tool_call(
                        index=0, call_id="call_1", name="tool_a", arguments='{"a": 1}'
                    ),
                    make_tool_call(
                        index=1, call_id="call_2", name="tool_b", arguments='{"b": 2}'
                    ),
                ],
                finish_reason="tool_calls",
            ),
        ]
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

    tc = result.choices[0].message.tool_calls
    assert tc is not None
    assert len(tc) == 2
    assert tc[0].id == "call_1"
    assert tc[0].function.name == "tool_a"  # type: ignore[possibly-missing-attribute]
    assert tc[1].id == "call_2"
    assert tc[1].function.name == "tool_b"  # type: ignore[possibly-missing-attribute]


async def test_on_first_text_callback_fires_once(mock_client: MagicMock):
    calls: list[bool] = []

    async def on_first_text() -> None:
        calls.append(True)

    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(content="Hello"),
            make_chunk(content=" world", finish_reason="stop"),
        ]
    )

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


async def test_empty_choices_skipped(mock_client: MagicMock):
    empty_chunk = MagicMock()
    empty_chunk.choices = []
    empty_chunk.usage = None

    mock_client.chat.completions.create = make_stream_mock(
        [
            empty_chunk,
            make_chunk(content="Hello", finish_reason="stop"),
        ]
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
    assert result.choices[0].message.content == "Hello"


async def test_none_delta_skipped(mock_client: MagicMock):
    no_delta = MagicMock()
    no_delta.choices = [MagicMock()]
    no_delta.choices[0].delta = None
    no_delta.usage = None

    mock_client.chat.completions.create = make_stream_mock(
        [
            no_delta,
            make_chunk(content="Hello", finish_reason="stop"),
        ]
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
    assert result.choices[0].message.content == "Hello"


async def test_empty_tool_arguments_default_to_empty_object(mock_client: MagicMock):
    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(
                tool_calls=[
                    make_tool_call(
                        index=0, call_id="call_123", name="no_args", arguments=""
                    )
                ],
                finish_reason="tool_calls",
            ),
        ]
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
    assert result.choices[0].message.tool_calls[0].function.arguments == "{}"  # type: ignore[index, union-attr]


async def test_invalid_json_arguments_default_to_empty_object(mock_client: MagicMock):
    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(
                tool_calls=[
                    make_tool_call(
                        index=0,
                        call_id="call_123",
                        name="bad_json",
                        arguments="not valid json{",
                    )
                ],
                finish_reason="tool_calls",
            ),
        ]
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
    assert result.choices[0].message.tool_calls[0].function.arguments == "{}"  # type: ignore[index, union-attr]


async def test_tools_passed_to_api(mock_client: MagicMock):
    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(content="Hello", finish_reason="stop"),
        ]
    )

    mock_tool = ToolDefinition(
        name="test_tool",
        description="A test tool",
        input_schema={"type": "object", "properties": {}},
    )

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


async def test_model_id_fallback_to_default(mock_client: MagicMock):
    model_empty = InferenceModel(model_id="", max_output_tokens=64_000)

    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(content="Hello", finish_reason="stop"),
        ]
    )

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
