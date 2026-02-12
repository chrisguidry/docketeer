"""Tests for ClaudeCodeBackend."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.brain.backend import BackendAuthError, BackendError, ContextTooLargeError
from docketeer.brain.claude_code_backend import (
    ClaudeCodeBackend,
    _build_bwrap_command,
    _check_error,
    _extract_text,
    _invoke_claude,
    _parse_response,
)
from docketeer.brain.core import InferenceModel

MODEL = InferenceModel(model_id="claude-opus-4-6", max_output_tokens=128_000)


# -- init --


def test_init_missing_bwrap():
    with (
        patch(
            "shutil.which",
            side_effect=lambda cmd: None if cmd == "bwrap" else "/usr/bin/claude",
        ),
        pytest.raises(BackendError, match="bwrap"),
    ):
        ClaudeCodeBackend(oauth_token="tok", claude_dir=Path("/tmp/test-claude"))


def test_init_missing_claude():
    with (
        patch(
            "shutil.which",
            side_effect=lambda cmd: "/usr/bin/bwrap" if cmd == "bwrap" else None,
        ),
        pytest.raises(BackendError, match="claude"),
    ):
        ClaudeCodeBackend(oauth_token="tok", claude_dir=Path("/tmp/test-claude"))


def test_init_creates_claude_dir(tmp_path: Path):
    claude_dir = tmp_path / "claude"
    with patch("shutil.which", return_value="/usr/bin/fake"):
        backend = ClaudeCodeBackend(oauth_token="tok", claude_dir=claude_dir)
    assert claude_dir.is_dir()
    assert backend.oauth_token == "tok"


# -- _extract_text --


def test_extract_text_string_content():
    assert _extract_text({"content": "hello"}) == "hello"


def test_extract_text_list_content():
    msg = {
        "content": [
            {"type": "text", "text": "line 1"},
            {"type": "text", "text": "line 2"},
        ]
    }
    assert _extract_text(msg) == "line 1\nline 2"


def test_extract_text_skips_non_text_blocks():
    msg = {
        "content": [
            {"type": "image", "source": {}},
            {"type": "text", "text": "visible"},
        ]
    }
    assert _extract_text(msg) == "visible"


def test_extract_text_raw_strings_in_list():
    assert _extract_text({"content": ["hello", "world"]}) == "hello\nworld"


def test_extract_text_empty():
    assert _extract_text({}) == ""


# -- _build_bwrap_command --


def test_bwrap_command_new_session():
    cmd = _build_bwrap_command(
        "claude-opus-4-6", "You are helpful.", "Hello!", Path("/tmp/claude")
    )
    assert cmd[0] == "bwrap"
    assert "--die-with-parent" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-6"
    assert cmd[cmd.index("--system-prompt") + 1] == "You are helpful."
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--dangerously-skip-permissions" in cmd
    assert "--resume" not in cmd


def test_bwrap_command_resume_omits_system_and_model():
    cmd = _build_bwrap_command(
        "claude-opus-4-6", "sys", "prompt", Path("/tmp/claude"), session_id="s1"
    )
    assert cmd[cmd.index("--resume") + 1] == "s1"
    assert "--system-prompt" not in cmd
    assert "--model" not in cmd


def test_bwrap_command_claude_dir_remap():
    home = Path.home()
    cmd = _build_bwrap_command("claude-opus-4-6", "sys", "prompt", Path("/data/claude"))
    bind_idx = next(
        i for i, a in enumerate(cmd) if a == "--bind" and cmd[i + 1] == "/data/claude"
    )
    assert cmd[bind_idx + 2] == str(home / ".claude")


# -- _parse_response --


def test_parse_response_text_and_session():
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Hello "}]},
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "world!"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "sess-42"}),
    ]
    text, session_id = _parse_response(lines)
    assert text == "Hello world!"
    assert session_id == "sess-42"


def test_parse_response_no_session():
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            }
        ),
        json.dumps({"type": "result"}),
    ]
    assert _parse_response(lines) == ("hi", None)


def test_parse_response_skips_tool_use():
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Let me check. "},
                        {"type": "tool_use", "name": "search", "input": {}},
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Done!"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    assert _parse_response(lines)[0] == "Let me check. Done!"


def test_parse_response_malformed_json():
    lines = ["not json", "", json.dumps({"type": "result", "session_id": "s1"})]
    assert _parse_response(lines) == ("", "s1")


def test_parse_response_empty():
    assert _parse_response([]) == ("", None)


# -- _check_error --


@pytest.mark.parametrize("stderr", ["unauthorized", "invalid token", "auth failure"])
def test_check_error_auth(stderr: str):
    with pytest.raises(BackendAuthError):
        _check_error(stderr, 1)


def test_check_error_context():
    with pytest.raises(ContextTooLargeError):
        _check_error("context window too large", 1)


def test_check_error_generic():
    with pytest.raises(BackendError):
        _check_error("something went wrong", 1)


# -- backend fixture + helpers --


@pytest.fixture()
def backend(tmp_path: Path) -> ClaudeCodeBackend:
    with patch("shutil.which", return_value="/usr/bin/fake"):
        return ClaudeCodeBackend(oauth_token="tok", claude_dir=tmp_path / "claude")


def _mock_tool_context(room_id: str = "room-1") -> AsyncMock:
    ctx = AsyncMock()
    ctx.room_id = room_id
    return ctx


def _patch_invoke(return_value: tuple[str, str | None]) -> patch:  # type: ignore[type-arg]
    return patch(
        "docketeer.brain.claude_code_backend._invoke_claude",
        new_callable=AsyncMock,
        return_value=return_value,
    )


# -- count_tokens --


async def test_count_tokens_returns_negative_one(backend: ClaudeCodeBackend):
    assert await backend.count_tokens("model", [], [], []) == -1


# -- run_agentic_loop session tracking --


async def test_first_call_sends_latest_message(backend: ClaudeCodeBackend):
    messages = [{"role": "user", "content": "@chris: hello"}]
    with _patch_invoke(("Hi Chris!", "sess-1")) as mock:
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
    assert mock.call_args[0][2] == "@chris: hello"
    assert mock.call_args[1].get("session_id") is None


async def test_subsequent_call_uses_resume(backend: ClaudeCodeBackend):
    messages: list[dict] = [{"role": "user", "content": "@chris: hello"}]
    tool_context = _mock_tool_context()
    with _patch_invoke(("Hi!", "sess-1")):
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
    messages.append({"role": "assistant", "content": "Hi!"})
    messages.append({"role": "user", "content": "@chris: how are you?"})
    with _patch_invoke(("Great!", "sess-1")) as mock:
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
    assert mock.call_args[0][2] == "@chris: how are you?"
    assert mock.call_args[1]["session_id"] == "sess-1"


async def test_compaction_resets_session(backend: ClaudeCodeBackend):
    messages: list[dict] = [
        {"role": "user", "content": "msg 1"},
        {"role": "assistant", "content": "reply 1"},
        {"role": "user", "content": "msg 2"},
    ]
    tool_context = _mock_tool_context()
    with _patch_invoke(("reply 2", "sess-1")):
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
    messages.clear()
    messages.append({"role": "user", "content": "compacted summary"})
    with _patch_invoke(("fresh reply", "sess-2")) as mock:
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
    assert mock.call_args[0][2] == "compacted summary"
    assert mock.call_args[1].get("session_id") is None


async def test_no_session_tracking_without_room_id(backend: ClaudeCodeBackend):
    messages = [{"role": "user", "content": "internal task"}]
    with _patch_invoke(("done", "sess-99")):
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


# -- utility_complete --


async def test_utility_complete(backend: ClaudeCodeBackend):
    with _patch_invoke(("summary text", None)) as mock:
        result = await backend.utility_complete("summarize this")
    assert result == "summary text"
    assert mock.call_args[0][2] == "summarize this"


# -- _invoke_claude subprocess --


async def test_invoke_claude_success():
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "hi"}]},
                }
            ),
            json.dumps({"type": "result", "session_id": "s1"}),
        ]
    )
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (stdout.encode(), b"")
    mock_proc.returncode = 0
    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "docketeer.brain.claude_code_backend._build_bwrap_command",
            return_value=["fake"],
        ),
    ):
        text, session_id = await _invoke_claude(
            "model", "sys", "prompt", "token", Path("/tmp/claude")
        )
    assert text == "hi"
    assert session_id == "s1"


async def test_invoke_claude_nonzero_exit():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"something went wrong")
    mock_proc.returncode = 1
    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "docketeer.brain.claude_code_backend._build_bwrap_command",
            return_value=["fake"],
        ),
    ):
        with pytest.raises(BackendError):
            await _invoke_claude("model", "sys", "prompt", "token", Path("/tmp/claude"))


async def test_invoke_claude_auth_error():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"unauthorized")
    mock_proc.returncode = 1
    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "docketeer.brain.claude_code_backend._build_bwrap_command",
            return_value=["fake"],
        ),
    ):
        with pytest.raises(BackendAuthError):
            await _invoke_claude("model", "sys", "prompt", "token", Path("/tmp/claude"))
