"""Build bwrap sandbox commands for claude -p."""

from __future__ import annotations

import os
from pathlib import Path

SYSTEM_RO_BINDS = [
    "/usr",
    "/bin",
    "/lib",
    "/lib64",
    "/etc/ssl",
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/alternatives",
]


def build_bwrap_command(
    model: str,
    system_text: str,
    prompt: str,
    claude_dir: Path,
    workspace: Path,
    claude_binary: Path,
    claude_install_root: Path,
    *,
    session_id: str | None = None,
    resume_session_id: str | None = None,
    mcp_config: str | None = None,
) -> list[str]:
    """Build the bwrap + claude -p command."""
    uid = os.getuid()
    gid = os.getgid()
    home = Path.home()

    args = ["bwrap", "--die-with-parent"]

    for path in SYSTEM_RO_BINDS:
        if Path(path).exists():  # pragma: no branch
            args.extend(["--ro-bind", path, path])

    args.extend(["--proc", "/proc"])
    args.extend(["--dev", "/dev"])
    args.extend(["--tmpfs", "/tmp"])

    # Empty home — no host files leak into the sandbox
    args.extend(["--tmpfs", str(home)])

    args.extend(["--bind", str(claude_dir), str(home / ".claude")])

    # Mount the claude binary's install root if not already under system paths
    if not any(claude_install_root.is_relative_to(p) for p in SYSTEM_RO_BINDS):
        args.extend(["--ro-bind", str(claude_install_root), str(claude_install_root)])

    args.extend(["--ro-bind", str(workspace), str(workspace)])

    args.extend(["--uid", str(uid), "--gid", str(gid)])
    args.extend(["--chdir", str(workspace)])

    args.extend(
        [
            str(claude_binary),
            "-p",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--dangerously-skip-permissions",
            "--disable-slash-commands",
        ]
    )

    if mcp_config:
        args.extend(["--mcp-config", mcp_config])
    else:
        args.extend(["--tools", ""])

    if resume_session_id:
        args.extend(["--resume", resume_session_id])
    else:
        if session_id:
            args.extend(["--session-id", session_id])
        args.extend(
            [
                "--system-prompt",
                system_text,
                "--model",
                model,
            ]
        )

    return args
