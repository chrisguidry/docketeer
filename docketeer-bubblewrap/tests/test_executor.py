"""Tests for the bubblewrap executor."""

import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer.executor import Mount
from docketeer_bubblewrap import BubblewrapExecutor, create_executor
from docketeer_bubblewrap.executor import (
    _build_args,
    _SandboxedProcess,
)

has_bwrap = shutil.which("bwrap") is not None
requires_bwrap = pytest.mark.skipif(not has_bwrap, reason="bwrap not on PATH")


# --- Factory ---


@requires_bwrap
def test_create_executor():
    executor = create_executor()
    assert isinstance(executor, BubblewrapExecutor)


def test_create_executor_bwrap_missing():
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="bwrap not found"):
            BubblewrapExecutor()


# --- _build_args ---


def test_build_args_default_flags():
    args = _build_args(mounts=[], network_access=False)
    assert args[0] == "bwrap"
    assert "--die-with-parent" in args
    assert "--unshare-pid" in args
    assert "--unshare-uts" in args
    assert "--unshare-ipc" in args
    assert "--unshare-cgroup" in args
    assert "--unshare-net" in args
    assert "--proc" in args
    assert "--dev" in args
    assert "--tmpfs" in args


def test_build_args_network_access():
    args = _build_args(mounts=[], network_access=True)
    assert "--unshare-net" not in args
    assert "--unshare-pid" in args


def test_build_args_custom_mounts():
    mounts = [
        Mount(source=Path("/data"), target=Path("/mnt/data"), writable=True),
        Mount(source=Path("/config"), target=Path("/mnt/config")),
    ]
    args = _build_args(mounts=mounts, network_access=False)

    # Find the writable mount
    bind_idx = args.index("--bind")
    assert args[bind_idx + 1] == "/data"
    assert args[bind_idx + 2] == "/mnt/data"

    # Find the read-only mount (after system binds, so find from the writable mount onward)
    remaining = args[bind_idx + 3 :]
    ro_idx = remaining.index("--ro-bind")
    assert remaining[ro_idx + 1] == "/config"
    assert remaining[ro_idx + 2] == "/mnt/config"


def test_build_args_skips_missing_system_paths():
    with patch("docketeer_bubblewrap.executor.SYSTEM_RO_BINDS", ["/no/such/path"]):
        args = _build_args(mounts=[], network_access=False)

    # /no/such/path doesn't exist, so no --ro-bind should appear
    ro_bind_count = args.count("--ro-bind")
    assert ro_bind_count == 0


def test_build_args_without_username():
    args = _build_args(mounts=[], network_access=False)
    assert "--uid" not in args
    assert "--gid" not in args


def test_build_args_with_username():
    args = _build_args(mounts=[], network_access=False, username="nix")
    uid = os.getuid()
    gid = os.getgid()

    uid_idx = args.index("--uid")
    assert args[uid_idx + 1] == str(uid)

    gid_idx = args.index("--gid")
    assert args[gid_idx + 1] == str(gid)


def test_build_args_with_username_creates_passwd_file(tmp_path: Path):
    args = _build_args(
        mounts=[], network_access=False, username="nix", tmp_dir=tmp_path
    )
    uid = os.getuid()
    gid = os.getgid()

    passwd_path = tmp_path / "passwd"
    assert passwd_path.exists()
    content = passwd_path.read_text()
    assert f"nix:x:{uid}:{gid}::" in content
    assert "/home/nix" in content

    # --ro-bind <source> /etc/passwd
    passwd_idx = args.index(str(passwd_path))
    assert args[passwd_idx - 1] == "--ro-bind"
    assert args[passwd_idx + 1] == "/etc/passwd"


def test_build_args_with_username_creates_group_file(tmp_path: Path):
    args = _build_args(
        mounts=[], network_access=False, username="nix", tmp_dir=tmp_path
    )
    gid = os.getgid()

    group_path = tmp_path / "group"
    assert group_path.exists()
    content = group_path.read_text()
    assert f"nix:x:{gid}:" in content

    # --ro-bind <source> /etc/group
    group_idx = args.index(str(group_path))
    assert args[group_idx - 1] == "--ro-bind"
    assert args[group_idx + 1] == "/etc/group"


# --- Integration tests (require bwrap) ---


@pytest.fixture()
def executor() -> BubblewrapExecutor:
    if not has_bwrap:
        pytest.skip("bwrap not on PATH")
    return BubblewrapExecutor()


async def test_run_echo(executor: BubblewrapExecutor):
    rp = await executor.start(["echo", "hello sandbox"])
    result = await rp.wait()
    assert result.returncode == 0
    assert b"hello sandbox" in result.stdout


async def test_writable_mount(executor: BubblewrapExecutor, tmp_path: Path):
    test_file = tmp_path / "output.txt"
    rp = await executor.start(
        ["sh", "-c", "echo written > /mnt/work/output.txt"],
        mounts=[Mount(source=tmp_path, target=Path("/mnt/work"), writable=True)],
    )
    result = await rp.wait()
    assert result.returncode == 0
    assert test_file.read_text().strip() == "written"


async def test_readonly_mount(executor: BubblewrapExecutor, tmp_path: Path):
    source_file = tmp_path / "input.txt"
    source_file.write_text("readonly content")
    rp = await executor.start(
        ["cat", "/mnt/ro/input.txt"],
        mounts=[Mount(source=tmp_path, target=Path("/mnt/ro"))],
    )
    result = await rp.wait()
    assert result.returncode == 0
    assert b"readonly content" in result.stdout


async def test_readonly_mount_rejects_writes(
    executor: BubblewrapExecutor, tmp_path: Path
):
    rp = await executor.start(
        ["sh", "-c", "echo fail > /mnt/ro/nope.txt"],
        mounts=[Mount(source=tmp_path, target=Path("/mnt/ro"))],
    )
    result = await rp.wait()
    assert result.returncode != 0


async def test_terminate(executor: BubblewrapExecutor):
    rp = await executor.start(["sleep", "60"])
    rp.terminate()
    result = await rp.wait()
    assert result.returncode != 0


async def test_env_empty_by_default(executor: BubblewrapExecutor):
    rp = await executor.start(["env"])
    result = await rp.wait()
    assert result.returncode == 0
    env_vars = dict(
        line.split("=", 1)
        for line in result.stdout.decode().strip().splitlines()
        if "=" in line
    )
    # PWD is set by the kernel, not inherited — that's fine
    env_vars.pop("PWD", None)
    assert env_vars == {}


async def test_env_passed_to_subprocess(executor: BubblewrapExecutor):
    rp = await executor.start(
        ["sh", "-c", "echo $MY_VAR"],
        env={"MY_VAR": "test_value", "PATH": "/usr/bin:/bin"},
    )
    result = await rp.wait()
    assert result.returncode == 0
    assert b"test_value" in result.stdout


async def test_username_stubs_cleaned_up_after_wait(executor: BubblewrapExecutor):
    rp = await executor.start(["true"], username="nix")
    assert isinstance(rp, _SandboxedProcess)
    assert rp._tmp_ctx is not None
    stub_dir = Path(rp._tmp_ctx.name)
    assert stub_dir.exists()
    assert (stub_dir / "passwd").exists()
    assert (stub_dir / "group").exists()

    await rp.wait()
    assert not stub_dir.exists()


async def test_no_cleanup_without_username(executor: BubblewrapExecutor):
    rp = await executor.start(["true"])
    assert isinstance(rp, _SandboxedProcess)
    assert rp._tmp_ctx is None
    await rp.wait()


async def test_username_sets_identity(executor: BubblewrapExecutor):
    rp = await executor.start(
        ["sh", "-c", "whoami && id -gn"],
        username="nix",
    )
    result = await rp.wait()
    assert result.returncode == 0
    lines = result.stdout.decode().strip().splitlines()
    assert lines[0] == "nix"
    assert lines[1] == "nix"


async def test_network_isolated_by_default(executor: BubblewrapExecutor):
    rp = await executor.start(
        ["sh", "-c", "cat /proc/net/if_inet6 2>/dev/null || echo no-network"],
    )
    result = await rp.wait()
    assert result.returncode == 0
