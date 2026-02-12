"""Tests for ClaudeCodeBackend."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.brain.backend import BackendError
from docketeer.brain.claude_code_backend import ClaudeCodeBackend
from docketeer.brain.core import InferenceModel

MODEL = InferenceModel(model_id="claude-opus-4-6", max_output_tokens=128_000)

FAKE_CLAUDE = Path("/opt/claude/versions/2.0.0")
FAKE_INSTALL_ROOT = Path("/opt/claude/versions")


# -- init --


@pytest.mark.parametrize("missing", ["bwrap", "claude", "socat"])
def test_init_missing_binary(missing: str):
    def which(cmd: str) -> str | None:
        return None if cmd == missing else "/usr/bin/fake"

    with (
        patch("shutil.which", side_effect=which),
        pytest.raises(BackendError, match=missing),
    ):
        ClaudeCodeBackend(oauth_token="tok", claude_dir=Path("/tmp/test-claude"))


def test_init_creates_claude_dir(tmp_path: Path):
    claude_dir = tmp_path / "claude"

    def which(cmd: str) -> str | None:
        return "/usr/bin/fake"

    with (
        patch("shutil.which", side_effect=which),
        patch(
            "docketeer.brain.claude_code_backend._find_install_root",
            return_value=FAKE_INSTALL_ROOT,
        ),
    ):
        backend = ClaudeCodeBackend(oauth_token="tok", claude_dir=claude_dir)
    assert claude_dir.is_dir()
    assert backend.oauth_token == "tok"


def test_init_resolves_claude_binary(tmp_path: Path):
    def which(cmd: str) -> str | None:
        return "/usr/bin/fake"

    with (
        patch("shutil.which", side_effect=which),
        patch(
            "docketeer.brain.claude_code_backend._find_install_root",
            return_value=FAKE_INSTALL_ROOT,
        ),
    ):
        backend = ClaudeCodeBackend(oauth_token="tok", claude_dir=tmp_path / "claude")
    assert backend._claude_binary == Path("/usr/bin/fake").resolve()
    assert backend._claude_install_root == FAKE_INSTALL_ROOT


def test_init_sets_mcp_fields_to_none(tmp_path: Path):
    with (
        patch("shutil.which", return_value="/usr/bin/fake"),
        patch(
            "docketeer.brain.claude_code_backend._find_install_root",
            return_value=FAKE_INSTALL_ROOT,
        ),
    ):
        backend = ClaudeCodeBackend(oauth_token="tok", claude_dir=tmp_path / "claude")
    assert backend._mcp_socket is None
    assert backend._mcp_config is None


# -- __aenter__ / __aexit__ --


async def test_aenter_binds_mcp_socket(tmp_path: Path):
    with (
        patch("shutil.which", return_value="/usr/bin/fake"),
        patch(
            "docketeer.brain.claude_code_backend._find_install_root",
            return_value=FAKE_INSTALL_ROOT,
        ),
    ):
        backend = ClaudeCodeBackend(oauth_token="tok", claude_dir=tmp_path / "claude")

    async with backend:
        assert backend._mcp_socket is not None
        assert backend._mcp_socket.is_serving
        assert backend._mcp_config is not None
        config = json.loads(backend._mcp_config)
        assert "docketeer" in config["mcpServers"]
        assert (tmp_path / "claude" / backend._socket_name).exists()

    assert backend._mcp_socket is None
    assert backend._mcp_config is None


async def test_aexit_cleans_up_socket_file(tmp_path: Path):
    with (
        patch("shutil.which", return_value="/usr/bin/fake"),
        patch(
            "docketeer.brain.claude_code_backend._find_install_root",
            return_value=FAKE_INSTALL_ROOT,
        ),
    ):
        backend = ClaudeCodeBackend(oauth_token="tok", claude_dir=tmp_path / "claude")

    async with backend:
        assert (tmp_path / "claude" / backend._socket_name).exists()

    assert not (tmp_path / "claude" / backend._socket_name).exists()


async def test_aexit_is_safe_without_aenter(tmp_path: Path):
    with (
        patch("shutil.which", return_value="/usr/bin/fake"),
        patch(
            "docketeer.brain.claude_code_backend._find_install_root",
            return_value=FAKE_INSTALL_ROOT,
        ),
    ):
        backend = ClaudeCodeBackend(oauth_token="tok", claude_dir=tmp_path / "claude")

    await backend.__aexit__(None, None, None)


# -- backend fixture + helpers --


@pytest.fixture()
def backend(tmp_path: Path) -> ClaudeCodeBackend:
    with (
        patch("shutil.which", return_value="/usr/bin/fake"),
        patch(
            "docketeer.brain.claude_code_backend._find_install_root",
            return_value=FAKE_INSTALL_ROOT,
        ),
    ):
        return ClaudeCodeBackend(oauth_token="tok", claude_dir=tmp_path / "claude")


def _mock_tool_context(
    room_id: str = "room-1", workspace: Path | None = None
) -> AsyncMock:
    ctx = AsyncMock()
    ctx.room_id = room_id
    ctx.workspace = workspace or Path("/data/workspace")
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


async def test_first_call_passes_tools_and_context(backend: ClaudeCodeBackend):
    messages = [{"role": "user", "content": "hello"}]
    tool_context = _mock_tool_context()
    fake_tools = [AsyncMock(name="tool1")]
    with _patch_invoke(("reply", "sess-1")) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            fake_tools,
            tool_context,
            Path("/tmp"),
            Path("/tmp"),
            None,
        )
    assert mock.call_args[1]["tools"] is fake_tools
    assert mock.call_args[1]["tool_context"] is tool_context


async def test_first_call_passes_workspace_and_audit_path(backend: ClaudeCodeBackend):
    messages = [{"role": "user", "content": "hello"}]
    workspace = Path("/my/workspace")
    tool_context = _mock_tool_context(workspace=workspace)
    audit_path = Path("/audit/dir")
    with _patch_invoke(("reply", "sess-1")) as mock:
        await backend.run_agentic_loop(
            MODEL,
            [],
            messages,
            [],
            tool_context,
            audit_path,
            Path("/tmp"),
            None,
        )
    # workspace and audit_path are positional args [5] and [6]
    assert mock.call_args[0][5] == workspace
    assert mock.call_args[0][6] == audit_path


async def test_first_call_passes_mcp_socket_and_config(backend: ClaudeCodeBackend):
    messages = [{"role": "user", "content": "hello"}]
    with _patch_invoke(("reply", "sess-1")) as mock:
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
    assert mock.call_args[1]["mcp_socket"] is backend._mcp_socket
    assert mock.call_args[1]["mcp_config"] is backend._mcp_config


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
    # scratch and audit dirs are created under claude_dir
    assert (backend.claude_dir / "scratch").is_dir()
    assert (backend.claude_dir / "audit").is_dir()
