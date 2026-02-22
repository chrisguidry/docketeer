"""Tests for agentic_loop function."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from docketeer_anthropic.loop import MAX_TOOL_ROUNDS, agentic_loop

from docketeer.tools import ToolContext

from .conftest import (
    MODEL,
    FakeStream,
    make_response,
    make_text_block,
    make_tool_block,
)


async def test_agentic_loop_single_text_response(
    mock_client: MagicMock, tool_context: ToolContext, tmp_path: "Any"
) -> None:
    """agentic_loop returns text from single response."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client.messages.stream.return_value = FakeStream(response)

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


async def test_agentic_loop_tool_use_flow(
    mock_client: MagicMock, tool_context: ToolContext, tmp_path: "Any"
) -> None:
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

    mock_client.messages.stream.side_effect = make_stream

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


async def test_agentic_loop_callbacks_fire(
    mock_client: MagicMock, tool_context: ToolContext, tmp_path: "Any"
) -> None:
    """agentic_loop fires callbacks appropriately."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    mock_client.messages.stream.return_value = FakeStream(response)

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


async def test_agentic_loop_tool_callbacks_fire(
    mock_client: MagicMock, tool_context: ToolContext, tmp_path: "Any"
) -> None:
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

    mock_client.messages.stream.side_effect = make_stream

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


async def test_agentic_loop_interrupted_stops_loop(
    mock_client: MagicMock, tool_context: ToolContext, tmp_path: "Any"
) -> None:
    """agentic_loop stops when interrupted event is set."""
    text_block = make_text_block("Hello!")
    response = make_response([text_block])

    interrupted = asyncio.Event()
    interrupted.set()

    mock_client.messages.stream.return_value = FakeStream(response)

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


async def test_agentic_loop_max_tokens_stop_reason(
    mock_client: MagicMock, tool_context: ToolContext, tmp_path: "Any"
) -> None:
    """agentic_loop handles max_tokens stop reason."""
    text_block = make_text_block("Partial...")
    response = make_response([text_block], stop_reason="max_tokens")

    mock_client.messages.stream.return_value = FakeStream(response)

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


async def test_agentic_loop_exhausted_tool_rounds_nudges(
    mock_client: MagicMock, tool_context: ToolContext, tmp_path: "Any"
) -> None:
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

    mock_client.messages.stream.side_effect = make_stream

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
