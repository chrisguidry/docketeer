"""Tests for execute_tools function."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from docketeer.tools import ToolContext
from docketeer_anthropic.loop import execute_tools

from .helpers import make_tool_block


async def test_execute_tools_success(tmp_path: Path) -> None:
    """execute_tools runs tools and returns results."""
    tool_block = make_tool_block(
        name="read_file", tool_id="t1", input_data={"path": "/tmp"}
    )
    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    with patch("docketeer_anthropic.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="file contents")

        results = await execute_tools([tool_block], tool_context, tmp_path / "audit")

    assert len(results) == 1
    assert results[0]["type"] == "tool_result"
    assert results[0]["tool_use_id"] == "t1"
    assert results[0]["content"] == "file contents"
    assert results[0]["is_error"] is False


async def test_execute_tools_marks_errors(tmp_path: Path) -> None:
    """execute_tools marks error results."""
    tool_block = make_tool_block(name="bad_tool", tool_id="t1")
    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    with patch("docketeer_anthropic.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="Error: something failed")

        results = await execute_tools([tool_block], tool_context, tmp_path / "audit")

    assert results[0]["is_error"] is True


async def test_execute_tools_multiple(tmp_path: Path) -> None:
    """execute_tools handles multiple tools."""
    tool_blocks = [
        make_tool_block(name="tool1", tool_id="t1"),
        make_tool_block(name="tool2", tool_id="t2"),
    ]
    tool_context = ToolContext(workspace=tmp_path, username="test-user")

    with patch("docketeer_anthropic.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="result")

        results = await execute_tools(tool_blocks, tool_context, tmp_path / "audit")

    assert len(results) == 2
