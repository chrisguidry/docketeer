"""Tests for _invoke_claude subprocess execution and MCP dispatch."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.brain.backend import BackendAuthError, BackendError
from docketeer.brain.claude_code_backend import _invoke_claude

FAKE_CLAUDE = Path("/opt/claude/versions/2.0.0")
FAKE_INSTALL_ROOT = Path("/opt/claude/versions")


def _mock_tool_context(
    room_id: str = "room-1", workspace: Path | None = None
) -> AsyncMock:
    ctx = AsyncMock()
    ctx.room_id = room_id
    ctx.workspace = workspace or Path("/data/workspace")
    return ctx


def _make_mock_proc(
    stdout_lines: list[str],
    stderr: bytes = b"",
    returncode: int = 0,
) -> AsyncMock:
    """Create a mock subprocess with streaming-compatible stdin/stdout/stderr."""
    mock_proc = AsyncMock()
    mock_proc.returncode = returncode
    mock_proc.pid = 12345

    # stdin: write and close are sync, drain is async
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()

    # stdout: StreamReader that yields lines
    reader = asyncio.StreamReader()
    for line in stdout_lines:
        reader.feed_data((line + "\n").encode())
    reader.feed_eof()
    mock_proc.stdout = reader

    # stderr: async read returning bytes
    stderr_mock = AsyncMock()
    stderr_mock.read = AsyncMock(return_value=stderr)
    mock_proc.stderr = stderr_mock

    # wait() returns when process exits
    mock_proc.wait = AsyncMock(return_value=returncode)

    return mock_proc


# -- _invoke_claude subprocess --


async def test_invoke_claude_success(tmp_path: Path):
    stdout_lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    mock_proc = _make_mock_proc(stdout_lines)
    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "docketeer.brain.claude_code_backend.build_bwrap_command",
            return_value=["fake"],
        ),
    ):
        text, session_id, result_event = await _invoke_claude(
            "model",
            "sys",
            "prompt",
            "token",
            Path("/tmp/claude"),
            tmp_path,
            tmp_path / "audit",
            FAKE_CLAUDE,
            FAKE_INSTALL_ROOT,
        )
    assert text == "hi"
    assert session_id == "s1"
    assert result_event is not None
    assert result_event["session_id"] == "s1"


async def test_invoke_claude_nonzero_exit(tmp_path: Path):
    mock_proc = _make_mock_proc([], stderr=b"something went wrong", returncode=1)
    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "docketeer.brain.claude_code_backend.build_bwrap_command",
            return_value=["fake"],
        ),
    ):
        with pytest.raises(BackendError):
            await _invoke_claude(
                "model",
                "sys",
                "prompt",
                "token",
                Path("/tmp/claude"),
                tmp_path,
                tmp_path / "audit",
                FAKE_CLAUDE,
                FAKE_INSTALL_ROOT,
            )


async def test_invoke_claude_auth_error(tmp_path: Path):
    mock_proc = _make_mock_proc([], stderr=b"unauthorized", returncode=1)
    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "docketeer.brain.claude_code_backend.build_bwrap_command",
            return_value=["fake"],
        ),
    ):
        with pytest.raises(BackendAuthError):
            await _invoke_claude(
                "model",
                "sys",
                "prompt",
                "token",
                Path("/tmp/claude"),
                tmp_path,
                tmp_path / "audit",
                FAKE_CLAUDE,
                FAKE_INSTALL_ROOT,
            )


# -- _invoke_claude MCP dispatch --


async def test_invoke_claude_dispatches_to_mcp_with_socket(tmp_path: Path):
    """When tools, tool_context, and mcp_socket are provided, dispatches to MCP path."""
    tool_context = _mock_tool_context()
    fake_tools = [AsyncMock()]
    fake_socket = AsyncMock()

    with (
        patch(
            "docketeer.brain.claude_code_backend._invoke_claude_with_mcp",
            new_callable=AsyncMock,
            return_value=("mcp result", "s1", None),
        ) as mock_mcp,
        patch(
            "docketeer.brain.claude_code_backend.build_bwrap_command",
            return_value=["fake-cmd"],
        ),
    ):
        text, session_id, _ = await _invoke_claude(
            "model",
            "sys",
            "prompt",
            "token",
            tmp_path,
            tmp_path,
            tmp_path / "audit",
            FAKE_CLAUDE,
            FAKE_INSTALL_ROOT,
            tools=fake_tools,
            tool_context=tool_context,
            mcp_socket=fake_socket,
            mcp_config='{"mcpServers":{}}',
        )

    assert text == "mcp result"
    assert session_id == "s1"
    mock_mcp.assert_called_once()
    assert mock_mcp.call_args[0][3] is fake_socket


async def test_invoke_claude_uses_simple_path_without_socket(tmp_path: Path):
    """Without mcp_socket, uses the simple path even if tools are provided."""
    tool_context = _mock_tool_context()
    fake_tools = [AsyncMock()]

    with (
        patch(
            "docketeer.brain.claude_code_backend._invoke_claude_simple",
            new_callable=AsyncMock,
            return_value=("simple result", "s1", None),
        ) as mock_simple,
    ):
        text, _, _ = await _invoke_claude(
            "model",
            "sys",
            "prompt",
            "token",
            tmp_path,
            tmp_path,
            tmp_path / "audit",
            FAKE_CLAUDE,
            FAKE_INSTALL_ROOT,
            tools=fake_tools,
            tool_context=tool_context,
            mcp_socket=None,
            mcp_config=None,
        )

    assert text == "simple result"
    mock_simple.assert_called_once()


async def test_invoke_claude_no_mcp_without_tools(tmp_path: Path):
    """Without tools, _invoke_claude uses the simple path."""
    with (
        patch(
            "docketeer.brain.claude_code_backend._invoke_claude_simple",
            new_callable=AsyncMock,
            return_value=("no tools", "s1", None),
        ) as mock_simple,
    ):
        text, _, _ = await _invoke_claude(
            "model",
            "sys",
            "prompt",
            "token",
            tmp_path,
            tmp_path,
            tmp_path / "audit",
            FAKE_CLAUDE,
            FAKE_INSTALL_ROOT,
            tools=[],
            tool_context=None,
        )

    assert text == "no tools"
    mock_simple.assert_called_once()


async def test_invoke_claude_mcp_config_only_passed_with_tools(tmp_path: Path):
    """mcp_config is only forwarded to bwrap when tools and tool_context are present."""
    stdout_lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    mock_proc = _make_mock_proc(stdout_lines)

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "docketeer.brain.claude_code_backend.build_bwrap_command",
            return_value=["fake"],
        ) as mock_bwrap,
    ):
        await _invoke_claude(
            "model",
            "sys",
            "prompt",
            "token",
            tmp_path,
            tmp_path,
            tmp_path / "audit",
            FAKE_CLAUDE,
            FAKE_INSTALL_ROOT,
            tools=[],
            tool_context=None,
            mcp_config='{"mcpServers":{}}',
        )

    assert mock_bwrap.call_args[1]["mcp_config"] is None


async def test_invoke_claude_forwards_session_id_to_bwrap(tmp_path: Path):
    """session_id is forwarded to build_bwrap_command."""
    stdout_lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    mock_proc = _make_mock_proc(stdout_lines)

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "docketeer.brain.claude_code_backend.build_bwrap_command",
            return_value=["fake"],
        ) as mock_bwrap,
    ):
        await _invoke_claude(
            "model",
            "sys",
            "prompt",
            "token",
            tmp_path,
            tmp_path,
            tmp_path / "audit",
            FAKE_CLAUDE,
            FAKE_INSTALL_ROOT,
            session_id="my-uuid",
        )

    assert mock_bwrap.call_args[1]["session_id"] == "my-uuid"
    assert mock_bwrap.call_args[1].get("resume_session_id") is None


async def test_invoke_claude_forwards_resume_session_id_to_bwrap(tmp_path: Path):
    """resume_session_id is forwarded to build_bwrap_command."""
    stdout_lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    mock_proc = _make_mock_proc(stdout_lines)

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "docketeer.brain.claude_code_backend.build_bwrap_command",
            return_value=["fake"],
        ) as mock_bwrap,
    ):
        await _invoke_claude(
            "model",
            "sys",
            "prompt",
            "token",
            tmp_path,
            tmp_path,
            tmp_path / "audit",
            FAKE_CLAUDE,
            FAKE_INSTALL_ROOT,
            resume_session_id="existing-sess",
        )

    assert mock_bwrap.call_args[1]["resume_session_id"] == "existing-sess"
    assert mock_bwrap.call_args[1].get("session_id") is None
