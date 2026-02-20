"""Tests for ClaudeCodeBackend init, context manager, count_tokens, utility_complete."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from docketeer_anthropic.claude_code_backend import ClaudeCodeBackend

from docketeer.brain.core import InferenceModel

MODEL = InferenceModel(model_id="claude-opus-4-6", max_output_tokens=128_000)


def _mock_executor() -> AsyncMock:
    return AsyncMock()


# -- init --


def test_init_creates_claude_dir(tmp_path: Path):
    claude_dir = tmp_path / "claude"
    backend = ClaudeCodeBackend(
        executor=_mock_executor(), oauth_token="tok", claude_dir=claude_dir
    )
    assert claude_dir.is_dir()
    assert backend.oauth_token == "tok"


def test_init_sets_mcp_fields_to_none(tmp_path: Path):
    backend = ClaudeCodeBackend(
        executor=_mock_executor(), oauth_token="tok", claude_dir=tmp_path / "claude"
    )
    assert backend._mcp_socket is None
    assert backend._mcp_socket_path is None


# -- __aenter__ / __aexit__ --


async def test_aenter_binds_mcp_socket(tmp_path: Path):
    backend = ClaudeCodeBackend(
        executor=_mock_executor(), oauth_token="tok", claude_dir=tmp_path / "claude"
    )
    async with backend:
        assert backend._mcp_socket is not None
        assert backend._mcp_socket.is_serving
        assert backend._mcp_socket_path is not None
        assert (tmp_path / "claude" / backend._socket_name).exists()

    assert backend._mcp_socket is None
    assert backend._mcp_socket_path is None


async def test_aexit_cleans_up_socket_file(tmp_path: Path):
    backend = ClaudeCodeBackend(
        executor=_mock_executor(), oauth_token="tok", claude_dir=tmp_path / "claude"
    )
    async with backend:
        assert (tmp_path / "claude" / backend._socket_name).exists()

    assert not (tmp_path / "claude" / backend._socket_name).exists()


async def test_aexit_is_safe_without_aenter(tmp_path: Path):
    backend = ClaudeCodeBackend(
        executor=_mock_executor(), oauth_token="tok", claude_dir=tmp_path / "claude"
    )
    await backend.__aexit__(None, None, None)


# -- backend fixture + helpers --


@pytest.fixture()
def backend(tmp_path: Path) -> ClaudeCodeBackend:
    return ClaudeCodeBackend(
        executor=_mock_executor(), oauth_token="tok", claude_dir=tmp_path / "claude"
    )


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
        "docketeer_anthropic.claude_code_backend._invoke_claude",
        new_callable=AsyncMock,
        return_value=return_value,
    )


# -- count_tokens --


async def test_count_tokens_returns_negative_one_initially(backend: ClaudeCodeBackend):
    assert await backend.count_tokens("model", [], [], []) == -1


async def test_count_tokens_returns_context_after_invocation(
    backend: ClaudeCodeBackend,
):
    result_event = {
        "type": "result",
        "session_id": "sess-1",
        "usage": {
            "input_tokens": 100,
            "cache_read_input_tokens": 5000,
            "cache_creation_input_tokens": 3000,
            "output_tokens": 200,
        },
    }
    messages = [{"role": "user", "content": "hello"}]
    with _patch_invoke(("reply", "sess-1", result_event)):
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
    assert await backend.count_tokens("model", [], [], []) == 8100


# -- utility_complete --


async def test_utility_complete(backend: ClaudeCodeBackend):
    with _patch_invoke(("summary text", None, None)) as mock:
        result = await backend.utility_complete("summarize this")
    assert result == "summary text"
    # The prompt is now the 4th positional arg (after executor, model, system_text)
    assert mock.call_args[0][3] == "summarize this"
    # scratch and audit dirs are created under claude_dir
    assert (backend.claude_dir / "scratch").is_dir()
    assert (backend.claude_dir / "audit").is_dir()
