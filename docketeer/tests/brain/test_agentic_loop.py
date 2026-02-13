"""Tests for ClaudeCodeBackend.run_agentic_loop: sessions, callbacks, usage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.brain.claude_code_backend import ClaudeCodeBackend
from docketeer.brain.core import InferenceModel

MODEL = InferenceModel(model_id="claude-opus-4-6", max_output_tokens=128_000)


def _mock_executor() -> AsyncMock:
    return AsyncMock()


def _mock_tool_context(
    room_id: str = "room-1", workspace: Path | None = None
) -> AsyncMock:
    ctx = AsyncMock()
    ctx.room_id = room_id
    ctx.workspace = workspace or Path("/data/workspace")
    return ctx


def _patch_invoke(
    return_value: tuple[str, str | None, dict | None],
) -> patch:  # type: ignore[type-arg]
    return patch(
        "docketeer.brain.claude_code_backend._invoke_claude",
        new_callable=AsyncMock,
        return_value=return_value,
    )


@pytest.fixture()
def backend(tmp_path: Path) -> ClaudeCodeBackend:
    return ClaudeCodeBackend(
        executor=_mock_executor(), oauth_token="tok", claude_dir=tmp_path / "claude"
    )


# -- session tracking --


async def test_first_call_sends_latest_message(backend: ClaudeCodeBackend):
    messages = [{"role": "user", "content": "@chris: hello"}]
    with _patch_invoke(("Hi Chris!", "sess-1", None)) as mock:
        result = await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(),
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    assert result == "Hi Chris!"
    assert mock.call_args[0][3] == "@chris: hello"
    assert mock.call_args[1].get("resume_session_id") is None


async def test_first_call_includes_history_in_prompt(backend: ClaudeCodeBackend):
    """New sessions include all prior messages so CC has conversation context."""
    messages = [
        {"role": "user", "content": "[21:10] @peps: earlier question"},
        {"role": "assistant", "content": "Earlier reply."},
        {"role": "user", "content": "[21:19] @peps: latest message"},
    ]
    with _patch_invoke(("reply", "sess-1", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(),
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    prompt = mock.call_args[0][3]
    assert "[21:10] @peps: earlier question" in prompt
    assert "[assistant] Earlier reply." in prompt
    assert "[21:19] @peps: latest message" in prompt


async def test_first_call_passes_workspace_from_tool_context(
    backend: ClaudeCodeBackend,
):
    messages = [{"role": "user", "content": "hello"}]
    workspace = Path("/my/workspace")
    tool_context = _mock_tool_context(workspace=workspace)
    with _patch_invoke(("reply", "sess-1", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            tool_context,
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    # workspace is positional arg [6]
    assert mock.call_args[0][6] == workspace


async def test_first_call_passes_audit_path(backend: ClaudeCodeBackend):
    messages = [{"role": "user", "content": "hello"}]
    audit_path = Path("/audit/dir")
    with _patch_invoke(("reply", "sess-1", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(),
            audit_path,
            Path("/tmp"),
            None,
        )
    # audit_path is positional arg [7]
    assert mock.call_args[0][7] == audit_path


async def test_first_call_no_mcp_without_tools(backend: ClaudeCodeBackend):
    """Without tools, MCP fields are not passed to _invoke_claude."""
    messages = [{"role": "user", "content": "hello"}]
    with _patch_invoke(("reply", "sess-1", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(),
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    assert mock.call_args[1]["mcp_socket"] is None
    assert mock.call_args[1]["mcp_socket_path"] is None


async def test_subsequent_call_uses_resume(backend: ClaudeCodeBackend):
    messages: list[dict] = [{"role": "user", "content": "@chris: hello"}]
    tool_context = _mock_tool_context()
    with _patch_invoke(("Hi!", "sess-1", None)) as first_mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            tool_context,
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    assigned_id = first_mock.call_args[1]["session_id"]

    messages.append({"role": "assistant", "content": "Hi!"})
    messages.append({"role": "user", "content": "@chris: how are you?"})
    with _patch_invoke(("Great!", "sess-1", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            tool_context,
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    assert mock.call_args[0][3] == "@chris: how are you?"
    assert mock.call_args[1]["resume_session_id"] == assigned_id


async def test_compaction_resets_session(backend: ClaudeCodeBackend):
    messages: list[dict] = [{"role": "user", "content": "msg 1"}]
    tool_context = _mock_tool_context()
    with _patch_invoke(("reply 1", "sess-1", None)):
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            tool_context,
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    messages.append({"role": "assistant", "content": "reply 1"})
    messages.append({"role": "user", "content": "msg 2"})
    with _patch_invoke(("reply 2", "sess-1", None)):
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            tool_context,
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    # Simulate compaction — messages shrink below stored count
    messages.clear()
    messages.append({"role": "user", "content": "compacted summary"})
    with _patch_invoke(("fresh reply", "sess-2", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            tool_context,
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    assert mock.call_args[0][3] == "compacted summary"
    assert mock.call_args[1].get("resume_session_id") is None


async def test_no_session_tracking_without_room_id(backend: ClaudeCodeBackend):
    messages = [{"role": "user", "content": "internal task"}]
    with _patch_invoke(("done", "sess-99", None)):
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(room_id=""),
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    assert backend._sessions == {}


# -- callbacks passthrough --


async def test_run_agentic_loop_passes_callbacks(backend: ClaudeCodeBackend):
    messages = [{"role": "user", "content": "hello"}]
    callbacks = AsyncMock()
    with _patch_invoke(("reply", "sess-1", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(),
            Path("/tmp"),
            Path("/tmp"),
            callbacks,
        )
    assert mock.call_args[1]["callbacks"] is callbacks


# -- usage recording --


async def test_run_agentic_loop_records_model_usage(
    backend: ClaudeCodeBackend, tmp_path: Path
):
    result_event = {
        "type": "result",
        "session_id": "sess-1",
        "modelUsage": {
            "claude-opus-4-6": {
                "inputTokens": 4,
                "outputTokens": 364,
                "cacheReadInputTokens": 56747,
                "cacheCreationInputTokens": 10788,
                "costUSD": 0.105,
            },
        },
        "total_cost_usd": 0.105,
        "duration_ms": 12345,
        "duration_api_ms": 10000,
        "num_turns": 3,
    }
    messages = [{"role": "user", "content": "hello"}]
    usage_path = tmp_path / "usage"
    with _patch_invoke(("reply", "sess-1", result_event)):
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(),
            Path("/tmp"),
            usage_path,
            None,
        )
    files = list(usage_path.glob("*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text().strip())
    assert record["model"] == "claude-opus-4-6"
    assert record["input_tokens"] == 4
    assert record["output_tokens"] == 364
    assert record["cache_read_input_tokens"] == 56747
    assert record["cache_creation_input_tokens"] == 10788


async def test_run_agentic_loop_skips_usage_without_model_usage(
    backend: ClaudeCodeBackend, tmp_path: Path
):
    result_event = {"type": "result", "session_id": "sess-1"}
    messages = [{"role": "user", "content": "hello"}]
    usage_path = tmp_path / "usage"
    with _patch_invoke(("reply", "sess-1", result_event)):
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(),
            Path("/tmp"),
            usage_path,
            None,
        )
    assert not usage_path.exists()


# -- pre-assigned session IDs --


async def test_new_session_gets_pre_assigned_session_id(backend: ClaudeCodeBackend):
    """New sessions pass a generated session_id to _invoke_claude."""
    messages = [{"role": "user", "content": "hello"}]
    with _patch_invoke(("reply", "sess-1", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(),
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    session_id = mock.call_args[1]["session_id"]
    assert session_id is not None
    assert len(session_id) > 0
    assert mock.call_args[1].get("resume_session_id") is None


async def test_pre_assigned_session_id_stored_immediately(backend: ClaudeCodeBackend):
    """The pre-assigned session_id is used for session tracking."""
    messages = [{"role": "user", "content": "hello"}]
    with _patch_invoke(("reply", "sess-from-result", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            _mock_tool_context(),
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    # The stored session should use the pre-assigned ID, not the result event's
    assigned_id = mock.call_args[1]["session_id"]
    stored = backend._sessions["room-1"]
    assert stored.session_id == assigned_id


async def test_resumed_session_passes_resume_session_id(backend: ClaudeCodeBackend):
    """Resumed sessions pass resume_session_id, not session_id."""
    tool_context = _mock_tool_context()
    messages: list[dict] = [{"role": "user", "content": "hello"}]
    with _patch_invoke(("Hi!", "sess-1", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            tool_context,
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    first_session_id = mock.call_args[1]["session_id"]

    messages.append({"role": "assistant", "content": "Hi!"})
    messages.append({"role": "user", "content": "follow up"})
    with _patch_invoke(("Great!", "sess-1", None)) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            tool_context,
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    assert mock.call_args[1]["resume_session_id"] == first_session_id
    assert mock.call_args[1].get("session_id") is None
