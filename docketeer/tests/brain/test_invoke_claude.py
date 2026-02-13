"""Tests for _invoke_claude subprocess execution and MCP dispatch."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.brain.backend import BackendAuthError, BackendError
from docketeer.brain.claude_code_backend import _build_claude_args, _invoke_claude
from docketeer.executor import ClaudeInvocation, RunningProcess


def _mock_executor(proc: RunningProcess) -> AsyncMock:
    """Create a mock executor whose start_claude returns the given process."""
    executor = AsyncMock()
    executor.start_claude = AsyncMock(return_value=proc)
    return executor


def _make_mock_proc(
    stdout_lines: list[str],
    stderr: bytes = b"",
    returncode: int = 0,
) -> RunningProcess:
    """Create a RunningProcess wrapping a mock subprocess."""
    mock_proc = AsyncMock()
    mock_proc.returncode = returncode
    mock_proc.pid = 12345

    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()

    reader = asyncio.StreamReader()
    for line in stdout_lines:
        reader.feed_data((line + "\n").encode())
    reader.feed_eof()
    mock_proc.stdout = reader

    stderr_mock = AsyncMock()
    stderr_mock.read = AsyncMock(return_value=stderr)
    mock_proc.stderr = stderr_mock

    mock_proc.wait = AsyncMock(return_value=returncode)

    return RunningProcess(mock_proc)


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
    proc = _make_mock_proc(stdout_lines)
    executor = _mock_executor(proc)
    text, session_id, result_event = await _invoke_claude(
        executor,
        "model",
        "sys",
        "prompt",
        "token",
        Path("/tmp/claude"),
        tmp_path,
        tmp_path / "audit",
    )
    assert text == "hi"
    assert session_id == "s1"
    assert result_event is not None
    assert result_event["session_id"] == "s1"
    executor.start_claude.assert_called_once()


async def test_invoke_claude_nonzero_exit(tmp_path: Path):
    proc = _make_mock_proc([], stderr=b"something went wrong", returncode=1)
    executor = _mock_executor(proc)
    with pytest.raises(BackendError):
        await _invoke_claude(
            executor,
            "model",
            "sys",
            "prompt",
            "token",
            Path("/tmp/claude"),
            tmp_path,
            tmp_path / "audit",
        )


async def test_invoke_claude_auth_error(tmp_path: Path):
    proc = _make_mock_proc([], stderr=b"unauthorized", returncode=1)
    executor = _mock_executor(proc)
    with pytest.raises(BackendAuthError):
        await _invoke_claude(
            executor,
            "model",
            "sys",
            "prompt",
            "token",
            Path("/tmp/claude"),
            tmp_path,
            tmp_path / "audit",
        )


# -- _invoke_claude MCP dispatch --


async def test_invoke_claude_dispatches_to_mcp_with_socket(tmp_path: Path):
    """When mcp_socket is provided, dispatches to MCP path."""
    fake_socket = AsyncMock()
    tool_context = AsyncMock()
    tool_context.room_id = "room-1"
    tool_context.workspace = tmp_path

    proc = _make_mock_proc([])
    executor = _mock_executor(proc)

    with patch(
        "docketeer.brain.claude_code_backend._invoke_claude_with_mcp",
        new_callable=AsyncMock,
        return_value=("mcp result", "s1", None),
    ) as mock_mcp:
        text, session_id, _ = await _invoke_claude(
            executor,
            "model",
            "sys",
            "prompt",
            "token",
            tmp_path,
            tmp_path,
            tmp_path / "audit",
            mcp_socket=fake_socket,
            mcp_socket_path=tmp_path / "mcp.sock",
            tool_context=tool_context,
        )

    assert text == "mcp result"
    assert session_id == "s1"
    mock_mcp.assert_called_once()


async def test_invoke_claude_uses_simple_path_without_socket(tmp_path: Path):
    """Without mcp_socket, uses the simple path."""
    stdout_lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "simple"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    proc = _make_mock_proc(stdout_lines)
    executor = _mock_executor(proc)

    text, _, _ = await _invoke_claude(
        executor,
        "model",
        "sys",
        "prompt",
        "token",
        tmp_path,
        tmp_path,
        tmp_path / "audit",
        mcp_socket=None,
    )

    assert text == "simple"


async def test_invoke_claude_no_mcp_without_tool_context(tmp_path: Path):
    """Without tool_context, uses the simple path even with mcp_socket."""
    stdout_lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "no ctx"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    proc = _make_mock_proc(stdout_lines)
    executor = _mock_executor(proc)

    text, _, _ = await _invoke_claude(
        executor,
        "model",
        "sys",
        "prompt",
        "token",
        tmp_path,
        tmp_path,
        tmp_path / "audit",
        mcp_socket=AsyncMock(),
        tool_context=None,
    )

    assert text == "no ctx"


async def test_invoke_claude_builds_invocation_with_mcp_socket_path(tmp_path: Path):
    """When mcp_socket is provided, ClaudeInvocation includes mcp_socket_path."""
    fake_socket = AsyncMock()
    tool_context = AsyncMock()
    tool_context.room_id = "room-1"
    socket_path = tmp_path / "mcp.sock"

    proc = _make_mock_proc([])
    executor = _mock_executor(proc)

    with patch(
        "docketeer.brain.claude_code_backend._invoke_claude_with_mcp",
        new_callable=AsyncMock,
        return_value=("result", "s1", None),
    ):
        await _invoke_claude(
            executor,
            "model",
            "sys",
            "prompt",
            "token",
            tmp_path,
            tmp_path,
            tmp_path / "audit",
            mcp_socket=fake_socket,
            mcp_socket_path=socket_path,
            tool_context=tool_context,
        )

    invocation = executor.start_claude.call_args[0][0]
    assert isinstance(invocation, ClaudeInvocation)
    assert invocation.mcp_socket_path == socket_path


async def test_invoke_claude_invocation_no_mcp_when_no_socket(tmp_path: Path):
    """Without mcp_socket, ClaudeInvocation has no mcp_socket_path."""
    stdout_lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    proc = _make_mock_proc(stdout_lines)
    executor = _mock_executor(proc)

    await _invoke_claude(
        executor,
        "model",
        "sys",
        "prompt",
        "token",
        tmp_path,
        tmp_path,
        tmp_path / "audit",
    )

    invocation = executor.start_claude.call_args[0][0]
    assert invocation.mcp_socket_path is None


# -- _build_claude_args --


def test_build_claude_args_with_resume_session_id():
    args = _build_claude_args("model", "sys", resume_session_id="sess-1")
    assert "--resume" in args
    assert args[args.index("--resume") + 1] == "sess-1"
    assert "--system-prompt" not in args
    assert "--model" not in args


def test_build_claude_args_with_session_id():
    args = _build_claude_args("model", "sys", session_id="sess-2")
    assert "--session-id" in args
    assert args[args.index("--session-id") + 1] == "sess-2"
    assert "--system-prompt" in args
    assert "--model" in args
