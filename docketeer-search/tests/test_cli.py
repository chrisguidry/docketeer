"""Tests for the reindex CLI."""

from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer_search.cli import _is_text_file, _walk_workspace, main, reindex
from docketeer_search.store import VectorStore
from tests.conftest import FakeEmbedder


def test_is_text_file(workspace: Path):
    (workspace / "text.md").write_text("hello")
    (workspace / "binary.dat").write_bytes(b"\x00\xff\xfe")
    assert _is_text_file(workspace / "text.md")
    assert not _is_text_file(workspace / "binary.dat")


def test_is_text_file_missing(workspace: Path):
    assert not _is_text_file(workspace / "nope.txt")


def test_walk_workspace_skips_noise_dirs(workspace: Path):
    (workspace / ".git" / "objects").mkdir(parents=True)
    (workspace / ".git" / "objects" / "abc").write_text("blob")
    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "mod.pyc").write_bytes(b"\x00")
    (workspace / "tmp").mkdir()
    (workspace / "tmp" / "scratch.txt").write_text("temp stuff")
    (workspace / ".venv" / "bin").mkdir(parents=True)
    (workspace / ".venv" / "bin" / "activate").write_text("#!/bin/bash")
    (workspace / "notes.md").write_text("hello")

    files = _walk_workspace(workspace)
    rel = [str(f.relative_to(workspace)) for f in files]
    assert "notes.md" in rel
    assert not any(".git" in r for r in rel)
    assert not any("__pycache__" in r for r in rel)
    assert not any("tmp" in r for r in rel)
    assert not any(".venv" in r for r in rel)


def test_walk_workspace_skips_binary(workspace: Path):
    (workspace / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    (workspace / "readme.md").write_text("hi")

    files = _walk_workspace(workspace)
    rel = [str(f.relative_to(workspace)) for f in files]
    assert "readme.md" in rel
    assert "img.png" not in rel


def test_reindex_indexes_text_files(workspace: Path, tmp_path: Path):
    (workspace / "a.md").write_text("alpha")
    (workspace / "b.md").write_text("beta")
    (workspace / "empty.md").write_text("")

    with (
        patch("docketeer_search.cli.Embedder", FakeEmbedder),
        patch("docketeer_search.cli.environment.DATA_DIR", tmp_path / "data"),
    ):
        count = reindex(workspace)

    assert count == 2
    db_path = tmp_path / "data" / "search" / "index.db"
    with VectorStore(db_path) as store:
        assert store.list_paths() == {"a.md", "b.md"}


def test_reindex_removes_stale_entries(workspace: Path, tmp_path: Path):
    db_path = tmp_path / "data" / "search" / "index.db"

    embedder = FakeEmbedder()
    with VectorStore(db_path) as store:
        vec = embedder.embed(["old content"])[0]
        store.upsert("deleted.md", vec, "old content")

    (workspace / "kept.md").write_text("still here")

    with (
        patch("docketeer_search.cli.Embedder", FakeEmbedder),
        patch("docketeer_search.cli.environment.DATA_DIR", tmp_path / "data"),
    ):
        reindex(workspace)

    with VectorStore(db_path) as store:
        paths = store.list_paths()
        assert "kept.md" in paths
        assert "deleted.md" not in paths


def test_reindex_empty_workspace(workspace: Path, tmp_path: Path):
    with (
        patch("docketeer_search.cli.Embedder", FakeEmbedder),
        patch("docketeer_search.cli.environment.DATA_DIR", tmp_path / "data"),
    ):
        count = reindex(workspace)
    assert count == 0


def test_main_no_args(capsys: pytest.CaptureFixture[str]):
    with patch("sys.argv", ["docketeer-search"]):
        main()
    captured = capsys.readouterr()
    assert "reindex" in captured.out


def test_main_reindex(workspace: Path, tmp_path: Path):
    (workspace / "doc.md").write_text("hello")
    with (
        patch("sys.argv", ["docketeer-search", "reindex"]),
        patch("docketeer_search.cli.Embedder", FakeEmbedder),
        patch("docketeer_search.cli.environment.WORKSPACE_PATH", workspace),
        patch("docketeer_search.cli.environment.DATA_DIR", tmp_path / "data"),
    ):
        main()


def test_main_reindex_missing_workspace(tmp_path: Path):
    missing = tmp_path / "nope"
    with (
        patch("sys.argv", ["docketeer-search", "reindex"]),
        patch("docketeer_search.cli.environment.WORKSPACE_PATH", missing),
        __import__("pytest").raises(SystemExit, match="1"),
    ):
        main()
