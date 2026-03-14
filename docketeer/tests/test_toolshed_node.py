"""Toolshed tests: node runtime discovery and npm global prefix."""

from pathlib import Path
from unittest.mock import patch

from docketeer.toolshed import (
    DiscoveredRuntime,
    RuntimeSpec,
    Toolshed,
    discover,
)


def test_discover_finds_node_in_nvm(tmp_path: Path):
    node_root = tmp_path / "nvm" / "versions" / "node" / "v20"
    node_bin = node_root / "bin" / "node"
    node_bin.parent.mkdir(parents=True)
    node_bin.touch()

    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd == "node":
            return str(node_bin)
        return None

    with patch("docketeer.toolshed.shutil.which", side_effect=fake_which):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].spec.name == "node"
    assert ts.runtimes[0].install_root == node_root


def test_discover_follows_symlinks(tmp_path: Path):
    real_node = tmp_path / "nvm" / "versions" / "v20" / "bin" / "node"
    real_node.parent.mkdir(parents=True)
    real_node.touch()

    link_dir = tmp_path / "links"
    link_dir.mkdir()
    link = link_dir / "node"
    link.symlink_to(real_node)

    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd == "node":
            return str(link)
        return None

    with patch("docketeer.toolshed.shutil.which", side_effect=fake_which):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].install_root == tmp_path / "nvm" / "versions" / "v20"


# --- npm global prefix ---


def test_discover_picks_up_npm_global_prefix(tmp_path: Path):
    node_root = tmp_path / "nvm" / "versions" / "node" / "v20"
    node_bin = node_root / "bin" / "node"
    node_bin.parent.mkdir(parents=True)
    node_bin.touch()

    npm_prefix = tmp_path / ".npm-global"
    (npm_prefix / "bin").mkdir(parents=True)

    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd == "node":
            return str(node_bin)
        return None

    with (
        patch("docketeer.toolshed.shutil.which", side_effect=fake_which),
        patch.dict("os.environ", {"NPM_CONFIG_PREFIX": str(npm_prefix)}),
    ):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].extra_roots == [npm_prefix]


def test_discover_npm_prefix_via_command_fallback(tmp_path: Path):
    node_root = tmp_path / "nvm" / "versions" / "node" / "v20"
    node_bin = node_root / "bin" / "node"
    node_bin.parent.mkdir(parents=True)
    node_bin.touch()

    npm_prefix = tmp_path / ".npm-global"
    (npm_prefix / "bin").mkdir(parents=True)

    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd == "node":
            return str(node_bin)
        return None

    with (
        patch("docketeer.toolshed.shutil.which", side_effect=fake_which),
        patch(
            "docketeer.toolshed._run_prefix_command",
            return_value=str(npm_prefix),
        ),
    ):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].extra_roots == [npm_prefix]


def test_discover_skips_npm_prefix_when_same_as_install_root(tmp_path: Path):
    node_root = tmp_path / "nvm" / "versions" / "node" / "v20"
    node_bin = node_root / "bin" / "node"
    node_bin.parent.mkdir(parents=True)
    node_bin.touch()

    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd == "node":
            return str(node_bin)
        return None

    with (
        patch("docketeer.toolshed.shutil.which", side_effect=fake_which),
        patch.dict("os.environ", {"NPM_CONFIG_PREFIX": str(node_root)}),
    ):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].extra_roots == []


def test_discover_skips_npm_prefix_when_not_a_dir(tmp_path: Path):
    node_root = tmp_path / "nvm" / "versions" / "node" / "v20"
    node_bin = node_root / "bin" / "node"
    node_bin.parent.mkdir(parents=True)
    node_bin.touch()

    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd == "node":
            return str(node_bin)
        return None

    with (
        patch("docketeer.toolshed.shutil.which", side_effect=fake_which),
        patch.dict("os.environ", {"NPM_CONFIG_PREFIX": "/nonexistent/path"}),
    ):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].extra_roots == []


def test_mounts_includes_extra_roots(tmp_path: Path):
    npm_prefix = tmp_path / "npm-global"
    npm_prefix.mkdir()
    spec = RuntimeSpec("node", ["node"], "NPM_CONFIG_CACHE", "NPM_CONFIG_PREFIX")
    rt = DiscoveredRuntime(
        spec=spec,
        install_root=tmp_path / "node-root",
        extra_roots=[npm_prefix],
    )
    ts = Toolshed(runtimes=[rt], cache_root=tmp_path / "cache")

    mounts = ts.mounts()
    assert len(mounts) == 3
    assert mounts[0].source == tmp_path / "node-root"
    assert mounts[1].source == npm_prefix
    assert mounts[1].writable is False
    assert mounts[2].target == Path("/cache/node")


def test_env_includes_extra_roots_in_path(tmp_path: Path):
    node_root = tmp_path / "node"
    (node_root / "bin").mkdir(parents=True)
    npm_prefix = tmp_path / "npm-global"
    (npm_prefix / "bin").mkdir(parents=True)

    spec = RuntimeSpec("node", ["node"], "NPM_CONFIG_CACHE", "NPM_CONFIG_PREFIX")
    rt = DiscoveredRuntime(
        spec=spec,
        install_root=node_root,
        extra_roots=[npm_prefix],
    )
    ts = Toolshed(runtimes=[rt], cache_root=tmp_path / "cache")

    env = ts.env()
    path_parts = env["PATH"].split(":")
    assert str(npm_prefix / "bin") == path_parts[0]
    assert str(node_root / "bin") == path_parts[1]
