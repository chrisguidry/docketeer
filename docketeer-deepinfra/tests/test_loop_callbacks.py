"""Tests for agentic loop callbacks."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.brain.core import InferenceModel
from docketeer.prompt import MessageParam
from docketeer.tools import ToolContext

MODEL = InferenceModel(
    model_id="meta-llama/Llama-3.3-70B-Instruct", max_output_tokens=64_000
)


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path, username="test-user")


async def test_tool_start_and_end_callbacks(tool_context: ToolContext, tmp_path: Path):
    from docketeer_deepinfra.loop import agentic_loop

    tool_started: list[str] = []
    tool_ended: list[bool] = []

    async def on_tool_start(name: str) -> None:
        tool_started.append(name)

    async def on_tool_end() -> None:
        tool_ended.append(True)

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.function = MagicMock()
    mock_tool_call.function.name = "list_files"
    mock_tool_call.function.arguments = "{}"

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
    mock_message_final.content = "Done"
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
            mock_exec.return_value = [{"content": "result", "tool_call_id": "call_123"}]
            mock_stream.side_effect = [mock_response_tool, mock_response_final]

            await agentic_loop(
                client=MagicMock(),
                model=MODEL,
                system=[],
                messages=[MessageParam(role="user", content="test")],
                tools=[],
                tool_context=tool_context,
                audit_path=tmp_path / "audit",
                usage_path=tmp_path / "usage",
                callbacks_on_first_text=None,
                callbacks_on_text=None,
                callbacks_on_tool_start=on_tool_start,
                callbacks_on_tool_end=on_tool_end,
                interrupted=None,
            )

    assert tool_started == ["list_files"]
    assert tool_ended == [True]
