"""Tests for docket task handlers."""

from pathlib import Path
from unittest.mock import patch

from docketeer_search.store import VectorStore
from docketeer_search.tasks import (
    SNIPPET_LENGTH,
    _db_path,
    do_index_file,
    do_remove_file,
)
from tests.conftest import FakeEmbedder


def test_db_path(workspace: Path):
    result = _db_path(workspace)
    assert result.name == "index.db"
    assert "search" in result.parts


async def test_index_file_embeds_and_stores(workspace: Path, tmp_path: Path):
    (workspace / "note.md").write_text("hello world")
    db_path = tmp_path / "data" / "search" / "index.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await do_index_file(path="note.md", workspace=workspace)

    with VectorStore(db_path) as store:
        assert store.list_paths() == {"note.md"}


async def test_index_file_skips_missing(workspace: Path, tmp_path: Path):
    db_path = tmp_path / "data" / "search" / "index.db"
    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await do_index_file(path="nope.md", workspace=workspace)

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()


async def test_index_file_skips_binary(workspace: Path, tmp_path: Path):
    (workspace / "bin.dat").write_bytes(b"\x00\x01\x02\xff\xfe")
    db_path = tmp_path / "data" / "search" / "index.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await do_index_file(path="bin.dat", workspace=workspace)

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()


async def test_index_file_skips_empty(workspace: Path, tmp_path: Path):
    (workspace / "empty.md").write_text("   \n  ")
    db_path = tmp_path / "data" / "search" / "index.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await do_index_file(path="empty.md", workspace=workspace)

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()


async def test_index_file_truncates_snippet(workspace: Path, tmp_path: Path):
    long_content = "x" * 1_000
    (workspace / "long.md").write_text(long_content)
    db_path = tmp_path / "data" / "search" / "index.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await do_index_file(path="long.md", workspace=workspace)

    embedder = FakeEmbedder()
    vec = embedder.embed([long_content])[0]
    with VectorStore(db_path) as store:
        results = store.query(vec, limit=1)
        assert len(results[0].snippet) == SNIPPET_LENGTH


async def test_remove_file_deletes_entry(workspace: Path, tmp_path: Path):
    (workspace / "gone.md").write_text("bye")
    db_path = tmp_path / "data" / "search" / "index.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await do_index_file(path="gone.md", workspace=workspace)
        await do_remove_file(path="gone.md", workspace=workspace)

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()
