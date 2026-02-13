"""Bubblewrap-based sandboxed command executor."""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

from docketeer.executor import (
    ClaudeInvocation,
    CommandExecutor,
    CompletedProcess,
    Mount,
    RunningProcess,
)
from docketeer.toolshed import Toolshed, _find_install_root

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


class _SandboxedProcess(RunningProcess):
    """RunningProcess that cleans up a temporary directory after the process exits."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        tmp_ctx: tempfile.TemporaryDirectory[str],
    ) -> None:
        super().__init__(process)
        self._tmp_ctx = tmp_ctx

    async def wait(self) -> CompletedProcess:
        result = await super().wait()
        self._tmp_ctx.cleanup()
        return result


class BubblewrapExecutor(CommandExecutor):
    """Runs commands inside a bubblewrap sandbox."""

    def __init__(self, toolshed: Toolshed | None = None) -> None:
        if not shutil.which("bwrap"):
            raise RuntimeError("bwrap not found on PATH")
        self._toolshed = toolshed

    async def start_claude(  # pragma: no cover — integration path
        self,
        invocation: ClaudeInvocation,
        *,
        env: dict[str, str] | None = None,
    ) -> RunningProcess:
        claude_path = shutil.which("claude")
        if not claude_path:
            raise RuntimeError("claude not found on PATH")
        claude_binary = Path(claude_path).resolve()
        claude_install_root = _find_install_root(claude_binary)

        args = _build_claude_args(invocation, claude_binary, claude_install_root)

        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        return RunningProcess(process)

    async def start(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        mounts: list[Mount] | None = None,
        network_access: bool = False,
        username: str | None = None,
    ) -> RunningProcess:
        tmp_ctx = tempfile.TemporaryDirectory()
        tmp_dir = Path(tmp_ctx.name)

        # Merge mounts: toolshed → HOME → caller
        merged_mounts: list[Mount] = []
        if self._toolshed:
            merged_mounts.extend(self._toolshed.mounts())

        sandbox_home = Path(f"/home/{username}") if username else Path("/home/sandbox")
        merged_mounts.append(Mount(source=tmp_dir, target=sandbox_home, writable=True))

        if mounts:
            merged_mounts.extend(mounts)

        # Merge env: toolshed → HOME → caller
        merged_env: dict[str, str] = {}
        if self._toolshed:
            merged_env.update(self._toolshed.env())
        merged_env["HOME"] = str(sandbox_home)
        if env:
            merged_env.update(env)

        args = _build_args(
            mounts=merged_mounts,
            network_access=network_access,
            username=username,
            tmp_dir=tmp_dir,
        )
        args.extend(command)

        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        return _SandboxedProcess(process, tmp_ctx)


def _build_args(
    *,
    mounts: list[Mount],
    network_access: bool,
    username: str | None = None,
    tmp_dir: Path | None = None,
) -> list[str]:
    args = ["bwrap", "--die-with-parent"]

    # Namespace isolation
    args.extend(["--unshare-pid", "--unshare-uts", "--unshare-ipc", "--unshare-cgroup"])
    if not network_access:
        args.append("--unshare-net")

    # Read-only system binds (skip paths that don't exist)
    for path in SYSTEM_RO_BINDS:
        if Path(path).exists():
            args.extend(["--ro-bind", path, path])

    # Virtual filesystems
    args.extend(["--proc", "/proc"])
    args.extend(["--dev", "/dev"])
    args.extend(["--tmpfs", "/tmp"])

    # Identity mapping
    if username:
        uid = os.getuid()
        gid = os.getgid()
        args.extend(["--uid", str(uid), "--gid", str(gid)])

        stub_dir = tmp_dir if tmp_dir else Path(tempfile.mkdtemp())

        passwd_file = stub_dir / "passwd"
        passwd_file.write_text(f"{username}:x:{uid}:{gid}::/home/{username}:/bin/sh\n")
        args.extend(["--ro-bind", str(passwd_file), "/etc/passwd"])

        group_file = stub_dir / "group"
        group_file.write_text(f"{username}:x:{gid}:\n")
        args.extend(["--ro-bind", str(group_file), "/etc/group"])

    # User-specified mounts
    for mount in mounts:
        flag = "--bind" if mount.writable else "--ro-bind"
        args.extend([flag, str(mount.source), str(mount.target)])

    return args


_MCP_BRIDGE_PATH = Path(__file__).resolve().parent / "mcp_bridge.py"
_SANDBOX_BRIDGE_PATH = "/opt/docketeer/mcp_bridge.py"


def _build_claude_args(
    invocation: ClaudeInvocation,
    claude_binary: Path,
    claude_install_root: Path,
) -> list[str]:
    """Build bwrap args for running claude -p in a sandbox."""
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
    args.extend(["--tmpfs", str(home)])

    args.extend(["--bind", str(invocation.claude_dir), str(home / ".claude")])

    if not any(claude_install_root.is_relative_to(p) for p in SYSTEM_RO_BINDS):
        args.extend(["--ro-bind", str(claude_install_root), str(claude_install_root)])

    args.extend(["--ro-bind", str(invocation.workspace), str(invocation.workspace)])

    if invocation.mcp_socket_path:
        args.extend(
            [
                "--ro-bind",
                str(_MCP_BRIDGE_PATH),
                _SANDBOX_BRIDGE_PATH,
            ]
        )

    args.extend(["--uid", str(uid), "--gid", str(gid)])
    args.extend(["--chdir", str(invocation.workspace)])

    args.append(str(claude_binary))

    if invocation.mcp_socket_path:
        sandbox_socket = str(home / ".claude" / invocation.mcp_socket_path.name)
        mcp_config = json.dumps(
            {
                "mcpServers": {
                    "docketeer": {
                        "command": "python3",
                        "args": [
                            _SANDBOX_BRIDGE_PATH,
                            sandbox_socket,
                        ],
                    }
                }
            }
        )
        args.extend(["--mcp-config", mcp_config])
    else:
        args.extend(["--tools", ""])

    args.extend(invocation.claude_args)

    return args
