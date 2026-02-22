"""Tests for agentic loop callbacks."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from docketeer.prompt import MessageParam
from docketeer.tools import ToolContext
from docketeer_deepinfra.loop import agentic_loop

from .conftest import MODEL, make_response, make_tool_call


async def test_tool_start_and_end_callbacks(tool_context: ToolContext, tmp_path: Path):
    tool_started: list[str] = []
    tool_ended: list[bool] = []

    async def on_tool_start(name: str) -> None:
        tool_started.append(name)

    async def on_tool_end() -> None:
        tool_ended.append(True)

    tc = make_tool_call(call_id="call_123", name="list_files")
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5

    tool_response = make_response(
        tool_calls=[tc], finish_reason="tool_calls", usage=mock_usage
    )
    final_response = make_response(content="Done", usage=mock_usage)

    with (
        patch(
            "docketeer_deepinfra.loop.stream_message", new_callable=AsyncMock
        ) as mock_stream,
        patch(
            "docketeer_deepinfra.loop.execute_tools", new_callable=AsyncMock
        ) as mock_exec,
    ):
        mock_exec.return_value = [{"content": "result", "tool_call_id": "call_123"}]
        mock_stream.side_effect = [tool_response, final_response]

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
