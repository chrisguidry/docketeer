"""Tests for _build_claude_args (start_claude internals)."""

import json
import os
from pathlib import Path

from docketeer.executor import ClaudeInvocation
from docketeer_bubblewrap.executor import _build_claude_args

FAKE_CLAUDE = Path("/opt/claude/bin/claude")
FAKE_INSTALL_ROOT = Path("/opt/claude")


def test_build_claude_args_basic():
    invocation = ClaudeInvocation(
        claude_args=["--model", "opus", "--system-prompt", "Be helpful."],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    assert args[0] == "bwrap"
    assert "--die-with-parent" in args
    assert str(FAKE_CLAUDE) in args
    assert args[args.index("--chdir") + 1] == "/data/workspace"


def test_build_claude_args_claude_dir_mapped_to_dot_claude():
    home = Path.home()
    invocation = ClaudeInvocation(
        claude_args=[],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    bind_idx = next(
        i for i, a in enumerate(args) if a == "--bind" and args[i + 1] == "/data/claude"
    )
    assert args[bind_idx + 2] == str(home / ".claude")


def test_build_claude_args_workspace_mounted_readonly():
    invocation = ClaudeInvocation(
        claude_args=[],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    ro_idx = next(
        i
        for i, a in enumerate(args)
        if a == "--ro-bind" and args[i + 1] == "/data/workspace"
    )
    assert args[ro_idx + 2] == "/data/workspace"


def test_build_claude_args_home_is_tmpfs():
    home = Path.home()
    invocation = ClaudeInvocation(
        claude_args=[],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    tmpfs_idx = next(
        i for i, a in enumerate(args) if a == "--tmpfs" and args[i + 1] == str(home)
    )
    assert tmpfs_idx > 0


def test_build_claude_args_mounts_install_root():
    invocation = ClaudeInvocation(
        claude_args=[],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    ro_idx = next(
        i
        for i, a in enumerate(args)
        if a == "--ro-bind" and args[i + 1] == str(FAKE_INSTALL_ROOT)
    )
    assert args[ro_idx + 2] == str(FAKE_INSTALL_ROOT)


def test_build_claude_args_skips_system_install_root():
    invocation = ClaudeInvocation(
        claude_args=[],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
    )
    args = _build_claude_args(invocation, Path("/usr/bin/claude"), Path("/usr/bin"))
    ro_binds = [
        (args[i + 1], args[i + 2]) for i, a in enumerate(args[:-2]) if a == "--ro-bind"
    ]
    user_mount = [
        src for src, dst in ro_binds if src == "/usr/bin" and dst == "/usr/bin"
    ]
    assert len(user_mount) == 0


def test_build_claude_args_no_mcp_appends_tools_empty():
    invocation = ClaudeInvocation(
        claude_args=["--model", "opus"],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
        mcp_socket_path=None,
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    assert "--tools" in args
    assert args[args.index("--tools") + 1] == ""
    assert "--mcp-config" not in args


def test_build_claude_args_with_mcp_socket(tmp_path: Path):
    socket_path = tmp_path / "mcp.sock"
    invocation = ClaudeInvocation(
        claude_args=["--model", "opus"],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
        mcp_socket_path=socket_path,
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    assert "--tools" in args
    assert args[args.index("--tools") + 1] == ""
    assert "--mcp-config" in args
    config = json.loads(args[args.index("--mcp-config") + 1])
    assert "docketeer" in config["mcpServers"]
    server_config = config["mcpServers"]["docketeer"]
    assert server_config["command"] == "python3"
    sandbox_socket = str(Path.home() / ".claude" / "mcp.sock")
    assert server_config["args"][-1] == sandbox_socket


def test_build_claude_args_with_mcp_mounts_bridge(tmp_path: Path):
    socket_path = tmp_path / "mcp.sock"
    invocation = ClaudeInvocation(
        claude_args=[],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
        mcp_socket_path=socket_path,
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    assert "/opt/docketeer/mcp_bridge.py" in args


def test_build_claude_args_uid_gid():
    uid = os.getuid()
    gid = os.getgid()
    invocation = ClaudeInvocation(
        claude_args=[],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    assert args[args.index("--uid") + 1] == str(uid)
    assert args[args.index("--gid") + 1] == str(gid)


def test_build_claude_args_includes_claude_args():
    invocation = ClaudeInvocation(
        claude_args=["--model", "opus", "--session-id", "abc"],
        claude_dir=Path("/data/claude"),
        workspace=Path("/data/workspace"),
    )
    args = _build_claude_args(invocation, FAKE_CLAUDE, FAKE_INSTALL_ROOT)
    claude_idx = args.index(str(FAKE_CLAUDE))
    tail = args[claude_idx + 1 :]
    assert "--model" in tail
    assert tail[tail.index("--model") + 1] == "opus"
    assert "--session-id" in tail
    assert tail[tail.index("--session-id") + 1] == "abc"
