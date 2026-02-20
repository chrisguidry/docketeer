"""Tests for stream_message function."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

from anthropic.types import TextBlock
from docketeer_anthropic.loop import stream_message

from docketeer.brain.core import InferenceModel
from docketeer.prompt import MessageParam, SystemBlock

MODEL = InferenceModel(model_id="claude-sonnet-4-5-20251001", max_output_tokens=64_000)


def make_text_block(text: str = "Hello!") -> MagicMock:
    """Create a mock text block."""
    block = MagicMock(spec=TextBlock)
    block.text = text
    return block


def make_response(
    content: Any, stop_reason: str = "end_turn", usage: Any = None
) -> MagicMock:
    """Create a mock response."""
    response = MagicMock()
    response.content = content if isinstance(content, list) else [content]
    response.stop_reason = stop_reason
    response.usage = usage or MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return response


class FakeStream:  # pragma: no cover
    """Fake stream context manager for testing."""

    def __init__(self, response: MagicMock) -> None:
        self._response = response
        self.text_stream = self._make_text_stream()

    def _make_text_stream(self) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for block in self._response.content:
                if hasattr(block, "text"):
                    yield block.text[:5] if len(block.text) > 5 else block.text

        return gen()

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    async def get_final_message(self) -> MagicMock:
        return self._response


async def test_stream_message_basic() -> None:
    """stream_message returns response from client."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream.return_value = FakeStream(response)

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
    )
    assert result is not None


async def test_stream_message_with_thinking() -> None:
    """stream_message passes thinking config when enabled."""
    model = InferenceModel(
        model_id="claude-sonnet-4-5-20251001",
        max_output_tokens=64_000,
    )
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
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


async def test_stream_message_serializes_system_blocks() -> None:
    """stream_message serializes SystemBlock objects."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
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


async def test_stream_message_serializes_messageparam() -> None:
    """stream_message serializes MessageParam objects."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
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


async def test_stream_message_with_on_first_text() -> None:
    """stream_message fires on_first_text callback."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
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


async def test_stream_message_empty_text_stream() -> None:
    """stream_message handles empty text_stream without calling on_first_text."""
    response = make_response([])  # No content blocks

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
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
    assert callback_calls == []  # Callback not called because text_stream was empty
