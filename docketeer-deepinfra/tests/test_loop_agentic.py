"""Tests for the main agentic loop."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.brain.core import InferenceModel
from docketeer.prompt import MessageParam, SystemBlock
from docketeer.tools import ToolContext
from docketeer_deepinfra.loop import agentic_loop

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


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path, username="test-user")


# -- via real stream_message (integration-ish) --


async def test_truncated_response_appends_length_warning(
    tool_context: ToolContext, tmp_path: Path
):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = "Hello"
    chunk.choices[0].delta.tool_calls = None
    chunk.choices[0].finish_reason = "length"

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk])

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
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = None
    chunk.choices[0].delta.tool_calls = None
    chunk.choices[0].finish_reason = "stop"

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk])

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
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = "Final response"
    chunk.choices[0].delta.tool_calls = None
    chunk.choices[0].finish_reason = "stop"

    mock_client = MagicMock()
    mock_client.chat.completions.create = make_stream_mock([chunk])

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

    tc = MagicMock()
    tc.index = 0
    tc.id = "call_1"
    tc.function = MagicMock()
    tc.function.name = "test_tool"
    tc.function.arguments = "{}"

    tool_chunk = MagicMock()
    tool_chunk.choices = [MagicMock()]
    tool_chunk.choices[0].delta = MagicMock()
    tool_chunk.choices[0].delta.content = None
    tool_chunk.choices[0].delta.tool_calls = [tc]
    tool_chunk.choices[0].finish_reason = "tool_calls"

    summary_chunk = MagicMock()
    summary_chunk.choices = [MagicMock()]
    summary_chunk.choices[0].delta = MagicMock()
    summary_chunk.choices[0].delta.content = "Here is a summary"
    summary_chunk.choices[0].delta.tool_calls = None
    summary_chunk.choices[0].finish_reason = "stop"

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


# -- via mocked stream_message (unit) --


async def test_tool_call_then_final_response(tool_context: ToolContext, tmp_path: Path):
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.function = MagicMock()
    mock_tool_call.function.name = "list_files"
    mock_tool_call.function.arguments = '{"path": "/"}'

    mock_message_tool = MagicMock()
    mock_message_tool.content = None
    mock_message_tool.tool_calls = [mock_tool_call]

    mock_choice_tool = MagicMock()
    mock_choice_tool.message = mock_message_tool
    mock_choice_tool.finish_reason = "tool_calls"

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5

    mock_response_tool = MagicMock()
    mock_response_tool.choices = [mock_choice_tool]
    mock_response_tool.usage = mock_usage

    mock_message_final = MagicMock()
    mock_message_final.content = "Found 2 files"
    mock_message_final.tool_calls = None

    mock_choice_final = MagicMock()
    mock_choice_final.message = mock_message_final
    mock_choice_final.finish_reason = "stop"

    mock_response_final = MagicMock()
    mock_response_final.choices = [mock_choice_final]
    mock_response_final.usage = mock_usage

    with patch(
        "docketeer_deepinfra.loop.stream_message", new_callable=AsyncMock
    ) as mock_stream:
        with patch(
            "docketeer_deepinfra.loop.execute_tools", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = [
                {"content": "file1\nfile2", "tool_call_id": "call_123"}
            ]
            mock_stream.side_effect = [mock_response_tool, mock_response_final]

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
