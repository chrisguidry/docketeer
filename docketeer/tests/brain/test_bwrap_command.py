"""Tests for _build_bwrap_command."""

from pathlib import Path

from docketeer.brain.claude_code_backend import _build_bwrap_command

FAKE_CLAUDE = Path("/opt/claude/versions/2.0.0")
FAKE_INSTALL_ROOT = Path("/opt/claude/versions")


def test_bwrap_command_new_session():
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "You are helpful.",
        "Hello!",
        Path("/tmp/claude"),
        Path("/data/workspace"),
        FAKE_CLAUDE,
        FAKE_INSTALL_ROOT,
    )
    assert cmd[0] == "bwrap"
    assert "--die-with-parent" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-6"
    assert cmd[cmd.index("--system-prompt") + 1] == "You are helpful."
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--dangerously-skip-permissions" in cmd
    assert "--resume" not in cmd
    assert "--mcp-config" not in cmd


def test_bwrap_command_uses_resolved_binary():
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "sys",
        "prompt",
        Path("/tmp/claude"),
        Path("/data/workspace"),
        FAKE_CLAUDE,
        FAKE_INSTALL_ROOT,
    )
    assert str(FAKE_CLAUDE) in cmd
    assert cmd[cmd.index(str(FAKE_CLAUDE))] != "claude"


def test_bwrap_command_mounts_install_root():
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "sys",
        "prompt",
        Path("/tmp/claude"),
        Path("/data/workspace"),
        FAKE_CLAUDE,
        FAKE_INSTALL_ROOT,
    )
    ro_idx = next(
        i
        for i, a in enumerate(cmd)
        if a == "--ro-bind" and cmd[i + 1] == str(FAKE_INSTALL_ROOT)
    )
    assert cmd[ro_idx + 2] == str(FAKE_INSTALL_ROOT)


def test_bwrap_command_skips_system_install_root():
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "sys",
        "prompt",
        Path("/tmp/claude"),
        Path("/data/workspace"),
        Path("/usr/bin/claude"),
        Path("/usr/bin"),
    )
    # /usr/bin is already under /usr system ro-bind, should not appear again
    ro_binds = [
        (cmd[i + 1], cmd[i + 2]) for i, a in enumerate(cmd[:-2]) if a == "--ro-bind"
    ]
    user_mount = [
        src for src, dst in ro_binds if src == "/usr/bin" and dst == "/usr/bin"
    ]
    assert len(user_mount) == 0


def test_bwrap_command_resume_omits_system_and_model():
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "sys",
        "prompt",
        Path("/tmp/claude"),
        Path("/data/workspace"),
        FAKE_CLAUDE,
        FAKE_INSTALL_ROOT,
        session_id="s1",
    )
    assert cmd[cmd.index("--resume") + 1] == "s1"
    assert "--system-prompt" not in cmd
    assert "--model" not in cmd


def test_bwrap_command_claude_dir_remap():
    home = Path.home()
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "sys",
        "prompt",
        Path("/data/claude"),
        Path("/data/workspace"),
        FAKE_CLAUDE,
        FAKE_INSTALL_ROOT,
    )
    bind_idx = next(
        i for i, a in enumerate(cmd) if a == "--bind" and cmd[i + 1] == "/data/claude"
    )
    assert cmd[bind_idx + 2] == str(home / ".claude")


def test_bwrap_command_workspace_mount_and_chdir():
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "sys",
        "prompt",
        Path("/tmp/claude"),
        Path("/data/workspace"),
        FAKE_CLAUDE,
        FAKE_INSTALL_ROOT,
    )
    ro_idx = next(
        i
        for i, a in enumerate(cmd)
        if a == "--ro-bind" and cmd[i + 1] == "/data/workspace"
    )
    assert cmd[ro_idx + 2] == "/data/workspace"
    assert cmd[cmd.index("--chdir") + 1] == "/data/workspace"


def test_bwrap_command_home_is_tmpfs():
    home = Path.home()
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "sys",
        "prompt",
        Path("/tmp/claude"),
        Path("/data/workspace"),
        FAKE_CLAUDE,
        FAKE_INSTALL_ROOT,
    )
    tmpfs_idx = next(
        i for i, a in enumerate(cmd) if a == "--tmpfs" and cmd[i + 1] == str(home)
    )
    assert tmpfs_idx > 0


def test_bwrap_command_with_mcp_config():
    mcp_config = '{"mcpServers":{"docketeer":{"command":"socat","args":["STDIO","UNIX-CONNECT:/tmp/test.sock"]}}}'
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "sys",
        "prompt",
        Path("/tmp/claude"),
        Path("/data/workspace"),
        FAKE_CLAUDE,
        FAKE_INSTALL_ROOT,
        mcp_config=mcp_config,
    )
    assert "--tools" not in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == mcp_config


def test_bwrap_command_mcp_config_with_resume():
    mcp_config = '{"mcpServers":{}}'
    cmd = _build_bwrap_command(
        "claude-opus-4-6",
        "sys",
        "prompt",
        Path("/tmp/claude"),
        Path("/data/workspace"),
        FAKE_CLAUDE,
        FAKE_INSTALL_ROOT,
        session_id="s1",
        mcp_config=mcp_config,
    )
    assert "--mcp-config" in cmd
    assert "--resume" in cmd
    assert "--tools" not in cmd
