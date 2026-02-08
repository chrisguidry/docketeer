"""Bubblewrap-based sandboxed command executor."""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from docketeer.executor import CommandExecutor, CompletedProcess, Mount, RunningProcess

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
        tmp_ctx: tempfile.TemporaryDirectory[str] | None,
    ) -> None:
        super().__init__(process)
        self._tmp_ctx = tmp_ctx

    async def wait(self) -> CompletedProcess:
        result = await super().wait()
        if self._tmp_ctx:
            self._tmp_ctx.cleanup()
        return result


class BubblewrapExecutor(CommandExecutor):
    """Runs commands inside a bubblewrap sandbox."""

    def __init__(self) -> None:
        if not shutil.which("bwrap"):
            raise RuntimeError("bwrap not found on PATH")

    async def start(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        mounts: list[Mount] | None = None,
        network_access: bool = False,
        username: str | None = None,
    ) -> RunningProcess:
        tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
        tmp_dir: Path | None = None
        if username:
            tmp_ctx = tempfile.TemporaryDirectory()
            tmp_dir = Path(tmp_ctx.name)

        args = _build_args(
            mounts=mounts or [],
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
            env=env or {},
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
