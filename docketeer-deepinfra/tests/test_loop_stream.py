"""Tests for stream_message in the agentic loop."""

from unittest.mock import MagicMock

from docketeer.brain.core import InferenceModel
from docketeer.prompt import MessageParam, SystemBlock
from docketeer.tools import ToolDefinition
from docketeer_deepinfra.loop import stream_message

from .conftest import MODEL, make_chunks, make_tc_delta, make_usage


async def test_basic_content(mock_client: MagicMock):
    mock_client.chat.completions.create.return_value = make_chunks(
        content="Hello world"
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


async def test_tool_calls_returned(mock_client: MagicMock):
    tc = make_tc_delta(call_id="call_abc", name="list", arguments='{"path": "/"}')
    mock_client.chat.completions.create.return_value = make_chunks(
        tool_calls=[tc], finish_reason="tool_calls"
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

    tool_calls = result.choices[0].message.tool_calls
    assert tool_calls is not None
    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call_abc"
    assert tool_calls[0].function.name == "list"  # type: ignore[union-attr]
    assert tool_calls[0].function.arguments == '{"path": "/"}'  # type: ignore[union-attr]


async def test_multiple_tool_calls(mock_client: MagicMock):
    tc_a = make_tc_delta(index=0, call_id="call_1", name="tool_a", arguments='{"a": 1}')
    tc_b = make_tc_delta(index=1, call_id="call_2", name="tool_b", arguments='{"b": 2}')
    mock_client.chat.completions.create.return_value = make_chunks(
        tool_calls=[tc_a, tc_b], finish_reason="tool_calls"
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

    tool_calls = result.choices[0].message.tool_calls
    assert tool_calls is not None
    assert len(tool_calls) == 2
    assert tool_calls[0].function.name == "tool_a"  # type: ignore[union-attr]
    assert tool_calls[1].function.name == "tool_b"  # type: ignore[union-attr]


async def test_on_first_text_callback_fires_once(mock_client: MagicMock):
    calls: list[bool] = []

    async def on_first_text() -> None:
        calls.append(True)

    mock_client.chat.completions.create.return_value = make_chunks(
        content="Hello world"
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


async def test_on_first_text_skipped_for_tool_only_response(mock_client: MagicMock):
    calls: list[bool] = []

    async def on_first_text() -> None:
        calls.append(True)  # pragma: no cover

    tc = make_tc_delta(call_id="call_1", name="test")
    mock_client.chat.completions.create.return_value = make_chunks(
        tool_calls=[tc], finish_reason="tool_calls"
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

    assert calls == []


async def test_tools_passed_to_api(mock_client: MagicMock):
    mock_client.chat.completions.create.return_value = make_chunks(content="Hello")

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
    mock_client.chat.completions.create.return_value = make_chunks(content="Hello")

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


async def test_usage_captured(mock_client: MagicMock):
    usage = make_usage(prompt_tokens=42, completion_tokens=7, total_tokens=49)
    mock_client.chat.completions.create.return_value = make_chunks(
        content="Hello", usage=usage
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
    assert result.usage is not None
    assert result.usage.prompt_tokens == 42
    assert result.usage.completion_tokens == 7


async def test_cached_tokens_captured(mock_client: MagicMock):
    usage = make_usage(
        prompt_tokens=100, completion_tokens=20, total_tokens=120, cached_tokens=80
    )
    mock_client.chat.completions.create.return_value = make_chunks(
        content="Hi", usage=usage
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
    assert result.usage is not None
    assert result.usage.prompt_tokens == 100
    assert result.usage.prompt_tokens_details is not None
    assert result.usage.prompt_tokens_details.cached_tokens == 80
