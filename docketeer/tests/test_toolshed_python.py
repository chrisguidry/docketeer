"""Toolshed tests: python/uv runtime discovery."""

from pathlib import Path
from unittest.mock import patch

from docketeer.toolshed import discover


def test_discover_finds_uv_in_local_bin(tmp_path: Path):
    uv_bin = tmp_path / ".local" / "bin" / "uv"
    uv_bin.parent.mkdir(parents=True)
    uv_bin.touch()

    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd in ("uvx", "uv"):
            return str(uv_bin)
        return None

    with (
        patch("docketeer.toolshed.shutil.which", side_effect=fake_which),
        patch("docketeer.toolshed.Path.home", return_value=tmp_path),
    ):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].spec.name == "python"
    assert ts.runtimes[0].install_root == tmp_path / ".local" / "bin"


def test_discover_deduplicates_roots(tmp_path: Path):
    uv_bin = tmp_path / ".local" / "bin" / "uv"
    uvx_bin = tmp_path / ".local" / "bin" / "uvx"
    uv_bin.parent.mkdir(parents=True)
    uv_bin.touch()
    uvx_bin.touch()

    def fake_which(cmd: str, **kwargs: object) -> str | None:
        if cmd == "uvx":
            return str(uvx_bin)
        if cmd == "uv":
            return str(uv_bin)  # pragma: no cover - not checked by discover
        return None  # pragma: no cover - defensive fallback

    with (
        patch("docketeer.toolshed.shutil.which", side_effect=fake_which),
        patch("docketeer.toolshed.Path.home", return_value=tmp_path),
    ):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].spec.name == "python"


def test_discover_skips_pyenv_shims(tmp_path: Path):
    shims_dir = tmp_path / ".pyenv" / "shims"
    shims_dir.mkdir(parents=True)
    shim = shims_dir / "uvx"
    shim.write_text("#!/bin/sh\nexec pyenv exec uvx\n")
    shim.chmod(0o755)

    real_dir = tmp_path / ".local" / "bin"
    real_dir.mkdir(parents=True)
    real_uvx = real_dir / "uvx"
    real_uvx.write_text("#!/bin/sh\n")
    real_uvx.chmod(0o755)

    path = f"{shims_dir}:{real_dir}"
    with (
        patch.dict("os.environ", {"PATH": path}),
        patch("docketeer.toolshed.Path.home", return_value=tmp_path),
    ):
        ts = discover(cache_root=tmp_path / "cache")

    assert len(ts.runtimes) == 1
    assert ts.runtimes[0].spec.name == "python"
    assert ts.runtimes[0].install_root == tmp_path / ".local" / "bin"
