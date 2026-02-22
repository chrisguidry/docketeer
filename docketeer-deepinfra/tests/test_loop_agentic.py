"""Tests for the main agentic loop."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.prompt import MessageParam, SystemBlock
from docketeer.tools import WRAP_UP_TOOL_NAME, ToolContext
from docketeer_deepinfra.loop import agentic_loop

from .conftest import (
    MODEL,
    AsyncStreamWrapper,
    make_chunk,
    make_response,
    make_stream_mock,
    make_tool_call,
    make_usage,
)

# -- via real stream_message (integration-ish) --


async def test_truncated_response_appends_length_warning(
    tool_context: ToolContext, tmp_path: Path
):
    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock(
        [make_chunk(content="Hello", finish_reason="length")]
    )

    result = await agentic_loop(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        tool_context=tool_context,
        audit_path=tmp_path / "audit",
        usage_path=tmp_path / "usage",
        callbacks_on_first_text=None,
        callbacks_on_text=None,
        callbacks_on_tool_start=None,
        callbacks_on_tool_end=None,
        interrupted=None,
    )

    assert "Hello" in result
    assert "length limit" in result


async def test_empty_response_returns_no_response(
    tool_context: ToolContext, tmp_path: Path
):
    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock(
        [make_chunk(finish_reason="stop")]
    )

    result = await agentic_loop(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        tool_context=tool_context,
        audit_path=tmp_path / "audit",
        usage_path=tmp_path / "usage",
        callbacks_on_first_text=None,
        callbacks_on_text=None,
        callbacks_on_tool_start=None,
        callbacks_on_tool_end=None,
        interrupted=None,
    )

    assert result == "(no response)"


async def test_normal_stop_returns_content(tool_context: ToolContext, tmp_path: Path):
    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock(
        [make_chunk(content="Final response", finish_reason="stop")]
    )

    result = await agentic_loop(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        tool_context=tool_context,
        audit_path=tmp_path / "audit",
        usage_path=tmp_path / "usage",
        callbacks_on_first_text=None,
        callbacks_on_text=None,
        callbacks_on_tool_start=None,
        callbacks_on_tool_end=None,
        interrupted=None,
    )

    assert result == "Final response"


async def test_tool_round_limit_triggers_summary(
    tool_context: ToolContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from docketeer_deepinfra import loop

    monkeypatch.setattr(loop, "MAX_TOOL_ROUNDS", 2)

    tool_chunk = make_chunk(
        tool_calls=[make_tool_call(index=0, call_id="call_1", name="test_tool")],
        finish_reason="tool_calls",
        usage=make_usage(cached_tokens=50),
    )
    summary_chunk = make_chunk(
        content="Here is a summary",
        finish_reason="stop",
        usage=make_usage(prompt_tokens=150, completion_tokens=20, total_tokens=170),
    )
    # Manually clear prompt_tokens_details to exercise the else branch
    summary_chunk.usage.prompt_tokens_details = None

    call_count = [0]

    async def side_effect(*args: object, **kwargs: object) -> AsyncStreamWrapper:
        call_count[0] += 1
        if call_count[0] <= 2:
            return AsyncStreamWrapper([tool_chunk])
        return AsyncStreamWrapper([summary_chunk])

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)

    with patch("docketeer_deepinfra.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="tool result")

        result = await agentic_loop(
            client=mock_client,
            model=MODEL,
            system=[],
            messages=[MessageParam(role="user", content="test")],
            tools=[],
            tool_context=tool_context,
            audit_path=tmp_path / "audit",
            usage_path=tmp_path / "usage",
            callbacks_on_first_text=None,
            callbacks_on_text=None,
            callbacks_on_tool_start=None,
            callbacks_on_tool_end=None,
            interrupted=None,
        )

    assert result == "Here is a summary"


async def test_tool_round_limit_triggers_summary_without_cached_tokens(
    tool_context: ToolContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Summary request when prompt_tokens_details has non-int cached_tokens."""
    from docketeer_deepinfra import loop

    monkeypatch.setattr(loop, "MAX_TOOL_ROUNDS", 2)

    tool_chunk = make_chunk(
        tool_calls=[make_tool_call(index=0, call_id="call_1", name="test_tool")],
        finish_reason="tool_calls",
        usage=make_usage(cached_tokens=50),
    )
    summary_chunk = make_chunk(
        content="Summary without cache",
        finish_reason="stop",
        usage=make_usage(prompt_tokens=150, completion_tokens=20, total_tokens=170),
    )
    # Override prompt_tokens_details with a mock whose cached_tokens isn't an int
    mock_details = MagicMock()
    mock_details.cached_tokens = "not_an_int"
    summary_chunk.usage.prompt_tokens_details = mock_details

    call_count = [0]

    async def side_effect(*args: object, **kwargs: object) -> AsyncStreamWrapper:
        call_count[0] += 1
        if call_count[0] <= 2:
            return AsyncStreamWrapper([tool_chunk])
        return AsyncStreamWrapper([summary_chunk])

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)

    with patch("docketeer_deepinfra.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="tool result")

        result = await agentic_loop(
            client=mock_client,
            model=MODEL,
            system=[],
            messages=[MessageParam(role="user", content="test")],
            tools=[],
            tool_context=tool_context,
            audit_path=tmp_path / "audit",
            usage_path=tmp_path / "usage",
            callbacks_on_first_text=None,
            callbacks_on_text=None,
            callbacks_on_tool_start=None,
            callbacks_on_tool_end=None,
            interrupted=None,
        )

    assert result == "Summary without cache"


async def test_tool_round_limit_triggers_summary_no_usage(
    tool_context: ToolContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Summary request when prompt_tokens_details has int cached_tokens."""
    from docketeer_deepinfra import loop

    monkeypatch.setattr(loop, "MAX_TOOL_ROUNDS", 2)

    tool_chunk = make_chunk(
        tool_calls=[make_tool_call(index=0, call_id="call_1", name="test_tool")],
        finish_reason="tool_calls",
        usage=make_usage(cached_tokens=50),
    )
    summary_chunk = make_chunk(
        content="Final summary",
        finish_reason="stop",
        usage=make_usage(
            prompt_tokens=150, completion_tokens=20, total_tokens=170, cached_tokens=100
        ),
    )

    call_count = [0]

    async def side_effect(*args: object, **kwargs: object) -> AsyncStreamWrapper:
        call_count[0] += 1
        if call_count[0] <= 2:
            return AsyncStreamWrapper([tool_chunk])
        return AsyncStreamWrapper([summary_chunk])

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)

    with patch("docketeer_deepinfra.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="tool result")

        result = await agentic_loop(
            client=mock_client,
            model=MODEL,
            system=[],
            messages=[MessageParam(role="user", content="test")],
            tools=[],
            tool_context=tool_context,
            audit_path=tmp_path / "audit",
            usage_path=tmp_path / "usage",
            callbacks_on_first_text=None,
            callbacks_on_text=None,
            callbacks_on_tool_start=None,
            callbacks_on_tool_end=None,
            interrupted=None,
        )

    assert result == "Final summary"


# -- via mocked stream_message (unit) --


async def test_tool_call_then_final_response(tool_context: ToolContext, tmp_path: Path):
    tool_call_mock = make_tool_call(
        call_id="call_123", name="list_files", arguments='{"path": "/"}'
    )
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_tokens_details = MagicMock()
    mock_tokens_details.cached_tokens = 5
    mock_usage.prompt_tokens_details = mock_tokens_details

    tool_response = make_response(
        tool_calls=[tool_call_mock], finish_reason="tool_calls", usage=mock_usage
    )
    final_response = make_response(content="Found 2 files", usage=mock_usage)

    with (
        patch(
            "docketeer_deepinfra.loop.stream_message", new_callable=AsyncMock
        ) as mock_stream,
        patch(
            "docketeer_deepinfra.loop.execute_tools", new_callable=AsyncMock
        ) as mock_exec,
    ):
        mock_exec.return_value = [
            {"content": "file1\nfile2", "tool_call_id": "call_123"}
        ]
        mock_stream.side_effect = [tool_response, final_response]

        result = await agentic_loop(
            client=MagicMock(),
            model=MODEL,
            system=[SystemBlock(text="You are helpful.")],
            messages=[MessageParam(role="user", content="list files")],
            tools=[],
            tool_context=tool_context,
            audit_path=tmp_path / "audit",
            usage_path=tmp_path / "usage",
            callbacks_on_first_text=None,
            callbacks_on_text=None,
            callbacks_on_tool_start=None,
            callbacks_on_tool_end=None,
            interrupted=None,
        )

    assert result == "Found 2 files"


async def test_interrupted_returns_empty(tool_context: ToolContext, tmp_path: Path):
    interrupted = asyncio.Event()
    interrupted.set()

    result = await agentic_loop(
        client=MagicMock(),
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


async def test_wrap_up_silently_returns_empty(
    tool_context: ToolContext, tmp_path: Path
):
    """wrap_up_silently tool call causes agentic_loop to return empty string."""
    tool_call_mock = make_tool_call(
        call_id="call_1", name=WRAP_UP_TOOL_NAME, arguments="{}"
    )
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_usage.prompt_tokens_details = None

    tool_response = make_response(
        tool_calls=[tool_call_mock], finish_reason="tool_calls", usage=mock_usage
    )

    with (
        patch(
            "docketeer_deepinfra.loop.stream_message", new_callable=AsyncMock
        ) as mock_stream,
        patch("docketeer_deepinfra.loop.registry") as mock_registry,
    ):
        mock_registry.execute = AsyncMock(return_value="Done — no message.")
        mock_stream.return_value = tool_response

        result = await agentic_loop(
            client=MagicMock(),
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
            interrupted=None,
        )

    assert result == ""
    assert mock_stream.call_count == 1


async def test_wrap_up_silently_preserves_history(
    tool_context: ToolContext, tmp_path: Path
):
    """Tool calls and results are appended to messages before returning."""
    tool_call_mock = make_tool_call(
        call_id="call_1", name=WRAP_UP_TOOL_NAME, arguments="{}"
    )
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_usage.prompt_tokens_details = None

    tool_response = make_response(
        tool_calls=[tool_call_mock], finish_reason="tool_calls", usage=mock_usage
    )

    messages: list[MessageParam] = []
    with (
        patch(
            "docketeer_deepinfra.loop.stream_message", new_callable=AsyncMock
        ) as mock_stream,
        patch("docketeer_deepinfra.loop.registry") as mock_registry,
    ):
        mock_registry.execute = AsyncMock(return_value="Done — no message.")
        mock_stream.return_value = tool_response

        await agentic_loop(
            client=MagicMock(),
            model=MODEL,
            system=[],
            messages=messages,
            tools=[],
            tool_context=tool_context,
            audit_path=tmp_path / "audit",
            usage_path=tmp_path / "usage",
            callbacks_on_first_text=None,
            callbacks_on_text=None,
            callbacks_on_tool_start=None,
            callbacks_on_tool_end=None,
            interrupted=None,
        )

    assert len(messages) == 2
    assert messages[0].role == "assistant"
    assert messages[1].role == "tool"


async def test_wrap_up_silently_with_other_tools(
    tool_context: ToolContext, tmp_path: Path
):
    """Other tools in the same batch execute before wrap_up takes effect."""
    read_call = make_tool_call(
        index=0, call_id="call_1", name="read_file", arguments="{}"
    )
    wrap_call = make_tool_call(
        index=1, call_id="call_2", name=WRAP_UP_TOOL_NAME, arguments="{}"
    )
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_usage.prompt_tokens_details = None

    tool_response = make_response(
        tool_calls=[read_call, wrap_call], finish_reason="tool_calls", usage=mock_usage
    )

    executed_tools: list[str] = []

    async def track_execute(name: str, args: dict, ctx: ToolContext) -> str:
        executed_tools.append(name)
        return "ok"

    with (
        patch(
            "docketeer_deepinfra.loop.stream_message", new_callable=AsyncMock
        ) as mock_stream,
        patch("docketeer_deepinfra.loop.registry") as mock_registry,
    ):
        mock_registry.execute = AsyncMock(side_effect=track_execute)
        mock_stream.return_value = tool_response

        result = await agentic_loop(
            client=MagicMock(),
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
            interrupted=None,
        )

    assert result == ""
    assert executed_tools == ["read_file", WRAP_UP_TOOL_NAME]
