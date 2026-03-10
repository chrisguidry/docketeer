"""Tests for stream_message and content block serialization."""

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

from anthropic.types import TextBlock, ToolUseBlock

from docketeer.brain.core import InferenceModel
from docketeer.prompt import MessageParam, SystemBlock
from docketeer_anthropic.loop import (
    _dump_content_block,
    _partition_system_messages,
    stream_message,
)

from .helpers import (
    MODEL,
    FakeStream,
    make_response,
    make_text_block,
    make_tool_block,
)


async def test_stream_message_basic(mock_client: MagicMock) -> None:
    """stream_message returns response from client."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client.messages.stream.return_value = FakeStream(response)

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
    )
    assert result is not None


async def test_stream_message_with_thinking(mock_client: MagicMock) -> None:
    """stream_message passes thinking config when enabled."""
    model = InferenceModel(
        model_id="claude-sonnet-4-5-20251001",
        max_output_tokens=64_000,
    )
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client.messages.stream.return_value = FakeStream(response)

    await stream_message(
        client=mock_client,
        model=model,
        system=[],
        messages=[],
        tools=[],
        thinking=True,
    )
    call_kwargs = mock_client.messages.stream.call_args[1]
    assert "thinking" in call_kwargs


async def test_stream_message_serializes_system_blocks(
    mock_client: MagicMock,
) -> None:
    """stream_message serializes SystemBlock objects."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client.messages.stream.return_value = FakeStream(response)

    system = [SystemBlock(text="system prompt")]
    await stream_message(
        client=mock_client,
        model=MODEL,
        system=system,
        messages=[],
        tools=[],
    )
    call_kwargs = mock_client.messages.stream.call_args[1]
    assert call_kwargs["system"] == [{"type": "text", "text": "system prompt"}]


async def test_stream_message_serializes_messageparam(
    mock_client: MagicMock,
) -> None:
    """stream_message serializes MessageParam objects."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client.messages.stream.return_value = FakeStream(response)

    messages = [MessageParam(role="user", content="hello")]
    await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=messages,
        tools=[],
    )
    call_kwargs = mock_client.messages.stream.call_args[1]
    assert call_kwargs["messages"] == [{"role": "user", "content": "hello"}]


async def test_stream_message_with_on_first_text(mock_client: MagicMock) -> None:
    """stream_message fires on_first_text callback."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client.messages.stream.return_value = FakeStream(response)

    callback_calls: list[bool] = []

    async def on_first_text() -> None:
        callback_calls.append(True)

    await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
        on_first_text=on_first_text,
    )
    assert callback_calls == [True]


async def test_stream_message_with_on_text(mock_client: MagicMock) -> None:
    """stream_message forwards incremental text chunks to on_text."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client.messages.stream.return_value = FakeStream(response)

    chunks: list[str] = []

    async def on_text(text: str) -> None:
        chunks.append(text)

    await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
        on_text=on_text,
    )
    assert chunks == ["Hello"]


async def test_stream_message_with_on_first_text_and_on_text(
    mock_client: MagicMock,
) -> None:
    """on_first_text fires once and on_text receives every stream chunk."""

    class _ChunkedStream(FakeStream):
        def _make_text_stream(self) -> AsyncIterator[str]:
            async def gen() -> AsyncIterator[str]:
                yield "Hel"
                yield "lo"
                yield "!"

            return gen()

    text_block = make_text_block("Hello!")
    response = make_response([text_block])
    mock_client.messages.stream.return_value = _ChunkedStream(response)

    events: list[str] = []

    async def on_first_text() -> None:
        events.append("first")

    async def on_text(text: str) -> None:
        events.append(text)

    await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
        on_first_text=on_first_text,
        on_text=on_text,
    )
    assert events == ["first", "Hel", "lo", "!"]


async def test_stream_message_skips_non_text_blocks(mock_client: MagicMock) -> None:
    """stream_message ignores non-text blocks in the text stream."""
    tool_block = make_tool_block()
    text_block = make_text_block("Hello!")
    response = make_response([tool_block, text_block])

    mock_client.messages.stream.return_value = FakeStream(response)

    callback_calls: list[bool] = []

    async def on_first_text() -> None:
        callback_calls.append(True)

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
        on_first_text=on_first_text,
    )
    assert result is not None
    assert callback_calls == [True]


async def test_stream_message_empty_text_stream(mock_client: MagicMock) -> None:
    """stream_message handles empty text_stream without calling on_first_text."""
    response = make_response([])

    mock_client.messages.stream.return_value = FakeStream(response)

    callback_calls: list[bool] = []

    async def on_first_text() -> (
        None
    ):  # pragma: no cover - never called when stream empty
        callback_calls.append(True)

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
        on_first_text=on_first_text,
    )
    assert result is not None
    assert callback_calls == []


def test_partition_system_messages_extracts_system_role():
    """System-role messages are moved to the system blocks list."""
    system = [SystemBlock(text="original")]
    messages = [
        MessageParam(role="system", content="injected context"),
        MessageParam(role="user", content="hello"),
        MessageParam(role="system", content="more context"),
        MessageParam(role="assistant", content="hi"),
    ]
    new_system, new_messages = _partition_system_messages(system, messages)
    assert len(new_system) == 3
    assert new_system[0].text == "original"
    assert new_system[1].text == "injected context"
    assert new_system[2].text == "more context"
    assert len(new_messages) == 2
    assert new_messages[0].role == "user"
    assert new_messages[1].role == "assistant"


def test_partition_system_messages_no_system_is_noop():
    """When there are no system-role messages, inputs pass through unchanged."""
    system = [SystemBlock(text="original")]
    messages = [MessageParam(role="user", content="hello")]
    new_system, new_messages = _partition_system_messages(system, messages)
    assert new_system is system
    assert new_messages is messages


async def test_stream_message_moves_system_messages_to_system_param(
    mock_client: MagicMock,
) -> None:
    """System-role messages in the conversation are sent as top-level system blocks."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])
    mock_client.messages.stream.return_value = FakeStream(response)

    messages = [
        MessageParam(role="system", content="injected context"),
        MessageParam(role="user", content="hello"),
    ]
    await stream_message(
        client=mock_client,
        model=MODEL,
        system=[SystemBlock(text="original")],
        messages=messages,
        tools=[],
    )
    call_kwargs = mock_client.messages.stream.call_args[1]
    assert len(call_kwargs["system"]) == 2
    assert call_kwargs["system"][0]["text"] == "original"
    assert call_kwargs["system"][1]["text"] == "injected context"
    assert len(call_kwargs["messages"]) == 1
    assert call_kwargs["messages"][0]["role"] == "user"


def test_dump_content_block_strips_extra_fields():
    """Extra fields from model_extra are excluded from serialization."""
    block = TextBlock.model_validate(
        {"type": "text", "text": "hi", "parsed_output": {"key": "value"}}
    )
    dumped = _dump_content_block(block)
    assert dumped == {"type": "text", "text": "hi"}
    assert "parsed_output" not in dumped


def test_dump_content_block_strips_none_values():
    """None values are excluded from serialization."""
    block = ToolUseBlock(type="tool_use", id="tool_1", name="test", input={"a": 1})
    dumped = _dump_content_block(block)
    assert "citations" not in dumped
    assert dumped["type"] == "tool_use"
    assert dumped["id"] == "tool_1"
    assert dumped["name"] == "test"
    assert dumped["input"] == {"a": 1}
