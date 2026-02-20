"""Tests for agentic_loop function."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from anthropic.types import TextBlock as AnthropicTextBlock
from anthropic.types import ToolUseBlock
from docketeer_anthropic.loop import MAX_TOOL_ROUNDS, agentic_loop

from docketeer.brain.core import InferenceModel
from docketeer.tools import ToolContext

MODEL = InferenceModel(model_id="claude-sonnet-4-5-20251001", max_output_tokens=64_000)


def make_text_block(text: str = "Hello!") -> MagicMock:
    """Create a mock text block."""
    block = MagicMock(spec=AnthropicTextBlock)
    block.text = text
    return block


def make_tool_block(
    name: str = "test_tool",
    tool_id: str = "tool_1",
    input_data: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock tool use block."""
    block = MagicMock(spec=ToolUseBlock)
    block.name = name
    block.id = tool_id
    block.input = input_data or {}
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


async def test_agentic_loop_single_text_response(tmp_path: Path) -> None:
    """agentic_loop returns text from single response."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream.return_value = FakeStream(response)

    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    result = await agentic_loop(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
        tool_context=tool_context,
        audit_path=tmp_path / "audit",
        usage_path=tmp_path / "usage",
        callbacks_on_first_text=None,
        callbacks_on_text=None,
        callbacks_on_tool_start=None,
        callbacks_on_tool_end=None,
    )
    assert "Hello!" in result


async def test_agentic_loop_tool_use_flow(tmp_path: Path) -> None:
    """agentic_loop executes tools and returns final text."""
    tool_block = make_tool_block(name="read_file", tool_id="t1")
    text_block = make_text_block("Done!")

    first_response = make_response([tool_block])
    second_response = make_response([text_block])

    call_count = 0

    def make_stream(*args: Any, **kwargs: Any) -> FakeStream:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FakeStream(first_response)
        return FakeStream(second_response)

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream.side_effect = make_stream

    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    with patch("docketeer_anthropic.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="file contents")

        result = await agentic_loop(
            client=mock_client,
            model=MODEL,
            system=[],
            messages=[],
            tools=[MagicMock()],
            tool_context=tool_context,
            audit_path=tmp_path / "audit",
            usage_path=tmp_path / "usage",
            callbacks_on_first_text=None,
            callbacks_on_text=None,
            callbacks_on_tool_start=None,
            callbacks_on_tool_end=None,
        )
    assert "Done!" in result


async def test_agentic_loop_callbacks_fire(tmp_path: Path) -> None:
    """agentic_loop fires callbacks appropriately."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream.return_value = FakeStream(response)

    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    first_text_called: list[bool] = []

    async def on_first_text() -> None:
        first_text_called.append(True)

    await agentic_loop(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
        tool_context=tool_context,
        audit_path=tmp_path / "audit",
        usage_path=tmp_path / "usage",
        callbacks_on_first_text=on_first_text,
        callbacks_on_text=None,
        callbacks_on_tool_start=None,
        callbacks_on_tool_end=None,
    )
    assert first_text_called == [True]


async def test_agentic_loop_tool_callbacks_fire(tmp_path: Path) -> None:
    """agentic_loop fires on_tool_start and on_tool_end callbacks."""
    tool_block = make_tool_block(name="read_file", tool_id="t1")
    text_block = make_text_block("Done!")

    first_response = make_response([tool_block])
    second_response = make_response([text_block])

    call_count = 0

    def make_stream(*args: Any, **kwargs: Any) -> FakeStream:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FakeStream(first_response)
        return FakeStream(second_response)

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream.side_effect = make_stream

    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    tool_start_calls: list[str] = []
    tool_end_calls: list[bool] = []

    async def on_tool_start(name: str) -> None:
        tool_start_calls.append(name)

    async def on_tool_end() -> None:
        tool_end_calls.append(True)

    with patch("docketeer_anthropic.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="result")

        await agentic_loop(
            client=mock_client,
            model=MODEL,
            system=[],
            messages=[],
            tools=[MagicMock()],
            tool_context=tool_context,
            audit_path=tmp_path / "audit",
            usage_path=tmp_path / "usage",
            callbacks_on_first_text=None,
            callbacks_on_text=None,
            callbacks_on_tool_start=on_tool_start,
            callbacks_on_tool_end=on_tool_end,
        )

    assert tool_start_calls == ["read_file"]
    assert tool_end_calls == [True]


async def test_agentic_loop_interrupted_stops_loop(tmp_path: Path) -> None:
    """agentic_loop stops when interrupted event is set."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    interrupted = asyncio.Event()
    interrupted.set()

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream.return_value = FakeStream(response)

    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    result = await agentic_loop(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
        tool_context=tool_context,
        audit_path=tmp_path / "audit",
        usage_path=tmp_path / "usage",
        callbacks_on_first_text=None,
        callbacks_on_text=None,
        callbacks_on_tool_start=None,
        callbacks_on_tool_end=None,
        interrupted=interrupted,
    )
    assert result == ""


async def test_agentic_loop_max_tokens_stop_reason(tmp_path: Path) -> None:
    """agentic_loop handles max_tokens stop reason."""
    text_block = make_text_block("Partial...")
    response = make_response([text_block], stop_reason="max_tokens")

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream.return_value = FakeStream(response)

    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    result = await agentic_loop(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[],
        tools=[],
        tool_context=tool_context,
        audit_path=tmp_path / "audit",
        usage_path=tmp_path / "usage",
        callbacks_on_first_text=None,
        callbacks_on_text=None,
        callbacks_on_tool_start=None,
        callbacks_on_tool_end=None,
    )
    assert "Partial" in result


async def test_agentic_loop_exhausted_tool_rounds_nudges(tmp_path: Path) -> None:
    """agentic_loop nudges for text after exhausting tool rounds."""
    responses = []
    for i in range(MAX_TOOL_ROUNDS):
        tool_block = make_tool_block(name="test", tool_id=f"t{i}")
        responses.append(make_response([tool_block]))
    text_block = make_text_block("Summary")
    responses.append(make_response([text_block]))

    call_count = 0

    def make_stream(*args: Any, **kwargs: Any) -> FakeStream:
        nonlocal call_count
        resp = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return FakeStream(resp)

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream.side_effect = make_stream

    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    with patch("docketeer_anthropic.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="result")

        result = await agentic_loop(
            client=mock_client,
            model=MODEL,
            system=[],
            messages=[],
            tools=[MagicMock()],
            tool_context=tool_context,
            audit_path=tmp_path / "audit",
            usage_path=tmp_path / "usage",
            callbacks_on_first_text=None,
            callbacks_on_text=None,
            callbacks_on_tool_start=None,
            callbacks_on_tool_end=None,
        )
    assert "Summary" in result
