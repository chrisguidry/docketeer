"""Tests for tool execution in the agentic loop."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.tools import ToolContext
from docketeer_deepinfra.loop import execute_tools


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path, username="test-user")


async def test_execute_tools_returns_results(tool_context: ToolContext, tmp_path: Path):
    tc = MagicMock()
    tc.id = "call_123"
    tc.function = MagicMock()
    tc.function.name = "list_files"
    tc.function.arguments = '{"path": "/"}'

    with patch("docketeer_deepinfra.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="file1.txt\nfile2.txt")
        results = await execute_tools([tc], tool_context, tmp_path / "audit")

    assert len(results) == 1
    assert results[0]["tool_call_id"] == "call_123"
    assert "file1.txt" in results[0]["content"]
    assert results[0]["is_error"] is False


async def test_invalid_json_args_falls_back_to_empty_dict(
    tool_context: ToolContext, tmp_path: Path
):
    tc = MagicMock()
    tc.id = "call_123"
    tc.function = MagicMock()
    tc.function.name = "list_files"
    tc.function.arguments = "not valid json{"

    with patch("docketeer_deepinfra.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="result")
        await execute_tools([tc], tool_context, tmp_path / "audit")
        mock_registry.execute.assert_called_once_with("list_files", {}, tool_context)


async def test_error_result_marked(tool_context: ToolContext, tmp_path: Path):
    tc = MagicMock()
    tc.id = "call_123"
    tc.function = MagicMock()
    tc.function.name = "list_files"
    tc.function.arguments = "{}"

    with patch("docketeer_deepinfra.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="Error: something went wrong")
        results = await execute_tools([tc], tool_context, tmp_path / "audit")

    assert results[0]["is_error"] is True


async def test_dict_args_passed_directly(tool_context: ToolContext, tmp_path: Path):
    tc = MagicMock()
    tc.id = "call_123"
    tc.function = MagicMock()
    tc.function.name = "list_files"
    tc.function.arguments = {"path": "/"}

    with patch("docketeer_deepinfra.loop.registry") as mock_registry:
        mock_registry.execute = AsyncMock(return_value="result")
        await execute_tools([tc], tool_context, tmp_path / "audit")
        mock_registry.execute.assert_called_once_with(
            "list_files", {"path": "/"}, tool_context
        )
