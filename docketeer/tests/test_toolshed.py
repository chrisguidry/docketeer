"""Toolshed tests: generic infrastructure (which, install_root, mounts, env, prefix)."""

from pathlib import Path
from unittest.mock import patch

from docketeer.toolshed import (
    DiscoveredRuntime,
    RuntimeSpec,
    Toolshed,
    _find_install_root,
    _resolve_global_prefix,
    _run_prefix_command,
    _which_skipping_shims,
    discover,
)

# --- _which_skipping_shims ---


def test_which_skipping_shims_finds_real_binary(tmp_path: Path):
    bin_dir = tmp_path / "real" / "bin"
    bin_dir.mkdir(parents=True)
    binary = bin_dir / "uv"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)

    with patch.dict("os.environ", {"PATH": str(bin_dir)}):
        result = _which_skipping_shims("uv")

    assert result is not None
    assert Path(result) == binary


def test_which_skipping_shims_skips_shim_dir(tmp_path: Path):
    shims_dir = tmp_path / ".pyenv" / "shims"
    shims_dir.mkdir(parents=True)
    shim = shims_dir / "uv"
    shim.write_text("#!/bin/sh\nexec pyenv exec uv\n")
    shim.chmod(0o755)

    real_dir = tmp_path / ".local" / "bin"
    real_dir.mkdir(parents=True)
    real_binary = real_dir / "uv"
    real_binary.write_text("#!/bin/sh\n")
    real_binary.chmod(0o755)

    path = f"{shims_dir}:{real_dir}"
    with patch.dict("os.environ", {"PATH": path}):
        result = _which_skipping_shims("uv")

    assert result is not None
    assert Path(result) == real_binary


def test_which_skipping_shims_returns_none_when_only_shim(tmp_path: Path):
    shims_dir = tmp_path / ".pyenv" / "shims"
    shims_dir.mkdir(parents=True)
    shim = shims_dir / "uv"
    shim.write_text("#!/bin/sh\nexec pyenv exec uv\n")
    shim.chmod(0o755)

    with patch.dict("os.environ", {"PATH": str(shims_dir)}):
        result = _which_skipping_shims("uv")

    assert result is None


def test_which_skipping_shims_returns_none_when_not_found(tmp_path: Path):
    with patch.dict("os.environ", {"PATH": str(tmp_path)}):
        result = _which_skipping_shims("nonexistent_tool_12345")

    assert result is None


# --- _find_install_root ---


def test_find_install_root_bin_dir(tmp_path: Path):
    binary = tmp_path / "lib" / "node" / "bin" / "node"
    binary.parent.mkdir(parents=True)
    binary.touch()
    assert _find_install_root(binary) == tmp_path / "lib" / "node"


def test_find_install_root_flat_dir(tmp_path: Path):
    binary = tmp_path / "tools" / "uv"
    binary.parent.mkdir(parents=True)
    binary.touch()
    assert _find_install_root(binary) == tmp_path / "tools"


def test_find_install_root_shared_prefix_local(tmp_path: Path):
    binary = tmp_path / ".local" / "bin" / "uv"
    binary.parent.mkdir(parents=True)
    binary.touch()
    with patch("docketeer.toolshed.Path.home", return_value=tmp_path):
        assert _find_install_root(binary) == tmp_path / ".local" / "bin"


def test_find_install_root_shared_prefix_home(tmp_path: Path):
    binary = tmp_path / "bin" / "uv"
    binary.parent.mkdir(parents=True)
    binary.touch()
    with patch("docketeer.toolshed.Path.home", return_value=tmp_path):
        assert _find_install_root(binary) == tmp_path / "bin"


# --- Toolshed.mounts ---


def test_mounts_empty():
    ts = Toolshed(runtimes=[], cache_root=Path("/cache"))
    assert ts.mounts() == []


def test_mounts_includes_ro_and_cache(tmp_path: Path):
    spec = RuntimeSpec("node", ["node"], "NPM_CONFIG_CACHE")
    rt = DiscoveredRuntime(spec=spec, install_root=tmp_path / "node-root")
    ts = Toolshed(runtimes=[rt], cache_root=tmp_path / "cache")

    mounts = ts.mounts()
    assert len(mounts) == 2

    ro_mount = mounts[0]
    assert ro_mount.source == tmp_path / "node-root"
    assert ro_mount.target == tmp_path / "node-root"
    assert ro_mount.writable is False

    cache_mount = mounts[1]
    assert cache_mount.source == tmp_path / "cache" / "node"
    assert cache_mount.target == Path("/cache/node")
    assert cache_mount.writable is True


def test_mounts_creates_cache_dirs(tmp_path: Path):
    spec = RuntimeSpec("python", ["uvx"], "UV_CACHE_DIR")
    rt = DiscoveredRuntime(spec=spec, install_root=tmp_path / "uv-root")
    ts = Toolshed(runtimes=[rt], cache_root=tmp_path / "cache")

    ts.mounts()
    assert (tmp_path / "cache" / "python").is_dir()


# --- Toolshed.env ---


def test_env_empty():
    ts = Toolshed(runtimes=[], cache_root=Path("/cache"))
    assert ts.env() == {}


def test_env_includes_path_and_cache_var(tmp_path: Path):
    node_root = tmp_path / "nvm" / "versions" / "node" / "v20"
    bin_dir = node_root / "bin"
    bin_dir.mkdir(parents=True)

    spec = RuntimeSpec("node", ["node"], "NPM_CONFIG_CACHE")
    rt = DiscoveredRuntime(spec=spec, install_root=node_root)
    ts = Toolshed(runtimes=[rt], cache_root=tmp_path / "cache")

    env = ts.env()
    assert env["NPM_CONFIG_CACHE"] == "/cache/node"
    path_parts = env["PATH"].split(":")
    assert str(bin_dir) == path_parts[0]
    assert "/usr/local/bin" in path_parts
    assert "/usr/bin" in path_parts
    assert "/bin" in path_parts


def test_env_uses_root_when_no_bin_subdir(tmp_path: Path):
    tool_dir = tmp_path / "tools"
    tool_dir.mkdir()

    spec = RuntimeSpec("python", ["uv"], "UV_CACHE_DIR")
    rt = DiscoveredRuntime(spec=spec, install_root=tool_dir)
    ts = Toolshed(runtimes=[rt], cache_root=tmp_path / "cache")

    env = ts.env()
    path_parts = env["PATH"].split(":")
    assert str(tool_dir) == path_parts[0]


def test_env_multiple_runtimes(tmp_path: Path):
    node_root = tmp_path / "node"
    (node_root / "bin").mkdir(parents=True)
    uv_root = tmp_path / "uv"
    (uv_root / "bin").mkdir(parents=True)

    node_spec = RuntimeSpec("node", ["node"], "NPM_CONFIG_CACHE")
    uv_spec = RuntimeSpec("python", ["uv"], "UV_CACHE_DIR")
    ts = Toolshed(
        runtimes=[
            DiscoveredRuntime(spec=node_spec, install_root=node_root),
            DiscoveredRuntime(spec=uv_spec, install_root=uv_root),
        ],
        cache_root=tmp_path / "cache",
    )

    env = ts.env()
    path_parts = env["PATH"].split(":")
    assert path_parts[0] == str(node_root / "bin")
    assert path_parts[1] == str(uv_root / "bin")
    assert env["NPM_CONFIG_CACHE"] == "/cache/node"
    assert env["UV_CACHE_DIR"] == "/cache/python"


# --- _run_prefix_command / _resolve_global_prefix ---


def test_run_prefix_command_returns_output(tmp_path: Path):
    result = _run_prefix_command(["echo", str(tmp_path)])
    assert result == str(tmp_path)


def test_run_prefix_command_returns_empty_on_failure():
    assert _run_prefix_command(["false"]) == ""


def test_run_prefix_command_returns_empty_on_missing_binary():
    assert _run_prefix_command(["nonexistent_binary_xyz"]) == ""


def test_resolve_global_prefix_env_var(tmp_path: Path):
    prefix = tmp_path / "npm-global"
    prefix.mkdir()
    spec = RuntimeSpec("node", ["node"], "NPM_CONFIG_CACHE", "NPM_CONFIG_PREFIX")
    with patch.dict("os.environ", {"NPM_CONFIG_PREFIX": str(prefix)}):
        result = _resolve_global_prefix(spec, set())
    assert result == prefix


def test_resolve_global_prefix_falls_back_to_command(tmp_path: Path):
    prefix = tmp_path / "npm-global"
    prefix.mkdir()
    spec = RuntimeSpec(
        "node",
        ["node"],
        "NPM_CONFIG_CACHE",
        global_prefix_command=["echo", str(prefix)],
    )
    result = _resolve_global_prefix(spec, set())
    assert result == prefix


def test_resolve_global_prefix_env_var_takes_precedence(tmp_path: Path):
    env_prefix = tmp_path / "env-prefix"
    env_prefix.mkdir()
    cmd_prefix = tmp_path / "cmd-prefix"
    cmd_prefix.mkdir()
    spec = RuntimeSpec(
        "node",
        ["node"],
        "NPM_CONFIG_CACHE",
        "NPM_CONFIG_PREFIX",
        ["echo", str(cmd_prefix)],
    )
    with patch.dict("os.environ", {"NPM_CONFIG_PREFIX": str(env_prefix)}):
        result = _resolve_global_prefix(spec, set())
    assert result == env_prefix


def test_resolve_global_prefix_skips_seen_roots(tmp_path: Path):
    prefix = tmp_path / "npm-global"
    prefix.mkdir()
    spec = RuntimeSpec("node", ["node"], "NPM_CONFIG_CACHE", "NPM_CONFIG_PREFIX")
    with patch.dict("os.environ", {"NPM_CONFIG_PREFIX": str(prefix)}):
        result = _resolve_global_prefix(spec, {prefix})
    assert result is None


# --- discover() (cross-runtime) ---


def test_discover_skips_system_commands_without_prefix():
    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd == "node":
            return "/usr/bin/node"
        return None

    with (
        patch("docketeer.toolshed.shutil.which", side_effect=fake_which),
        patch("docketeer.toolshed._run_prefix_command", return_value=""),
    ):
        ts = discover(cache_root=Path("/tmp/cache"))

    assert len(ts.runtimes) == 0


def test_discover_skips_missing_commands():
    with patch("docketeer.toolshed.shutil.which", return_value=None):
        ts = discover(cache_root=Path("/tmp/cache"))

    assert len(ts.runtimes) == 0


def test_discover_finds_both_runtimes(tmp_path: Path):
    node_bin = tmp_path / "nvm" / "bin" / "node"
    node_bin.parent.mkdir(parents=True)
    node_bin.touch()

    uv_bin = tmp_path / ".local" / "bin" / "uvx"
    uv_bin.parent.mkdir(parents=True)
    uv_bin.touch()

    def fake_which(cmd: str, *, path: str = "") -> str | None:
        if cmd == "node":
            return str(node_bin)
        if cmd == "uvx":
            return str(uv_bin)
        return None  # pragma: no cover - defensive fallback

    with (
        patch("docketeer.toolshed.shutil.which", side_effect=fake_which),
        patch("docketeer.toolshed.Path.home", return_value=tmp_path),
        patch("docketeer.toolshed._run_prefix_command", return_value=""),
    ):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 2
    names = {r.spec.name for r in ts.runtimes}
    assert names == {"node", "python"}


def test_discover_skips_duplicate_roots_across_runtimes(tmp_path: Path):
    shared_bin = tmp_path / ".local" / "bin"
    shared_bin.mkdir(parents=True)
    (shared_bin / "node").touch()
    (shared_bin / "uvx").touch()

    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd == "node":
            return str(shared_bin / "node")
        if cmd == "uvx":
            return str(shared_bin / "uvx")
        return None  # pragma: no cover - defensive fallback

    with (
        patch("docketeer.toolshed.shutil.which", side_effect=fake_which),
        patch("docketeer.toolshed.Path.home", return_value=tmp_path),
        patch("docketeer.toolshed._run_prefix_command", return_value=""),
    ):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].spec.name == "node"
