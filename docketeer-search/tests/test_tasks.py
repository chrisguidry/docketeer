"""Tests for docket task handlers."""

from pathlib import Path
from unittest.mock import patch

from docketeer_search.store import VectorStore
from docketeer_search.tasks import (
    SNIPPET_LENGTH,
    _db_path,
    deindex,
    index,
)
from tests.conftest import FakeEmbedder


def test_db_path_default():
    result = _db_path("workspace")
    assert result.name == "workspace.db"
    assert "search" in result.parts


def test_db_path_custom_name():
    result = _db_path("mcp-tools")
    assert result.name == "mcp-tools.db"


async def test_index_embeds_and_stores(workspace: Path, tmp_path: Path):
    (workspace / "note.md").write_text("hello world")
    db_path = tmp_path / "data" / "search" / "workspace.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(
            index_name="workspace", path="note.md", file="note.md", workspace=workspace
        )

    with VectorStore(db_path) as store:
        assert store.list_paths() == {"note.md"}


async def test_index_skips_missing_file(workspace: Path, tmp_path: Path):
    db_path = tmp_path / "data" / "search" / "workspace.db"
    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(
            index_name="workspace", path="nope.md", file="nope.md", workspace=workspace
        )

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()


async def test_index_skips_binary_file(workspace: Path, tmp_path: Path):
    (workspace / "bin.dat").write_bytes(b"\x00\x01\x02\xff\xfe")
    db_path = tmp_path / "data" / "search" / "workspace.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(
            index_name="workspace", path="bin.dat", file="bin.dat", workspace=workspace
        )

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()


async def test_index_skips_empty_file(workspace: Path, tmp_path: Path):
    (workspace / "empty.md").write_text("   \n  ")
    db_path = tmp_path / "data" / "search" / "workspace.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(
            index_name="workspace",
            path="empty.md",
            file="empty.md",
            workspace=workspace,
        )

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()


async def test_index_truncates_snippet(workspace: Path, tmp_path: Path):
    long_content = "x" * 1_000
    (workspace / "long.md").write_text(long_content)
    db_path = tmp_path / "data" / "search" / "workspace.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(
            index_name="workspace", path="long.md", file="long.md", workspace=workspace
        )

    embedder = FakeEmbedder()
    vec = embedder.embed([long_content])[0]
    with VectorStore(db_path) as store:
        results = store.query(vec, limit=1)
        assert len(results[0].snippet) == SNIPPET_LENGTH


async def test_index_with_custom_index_name(workspace: Path, tmp_path: Path):
    (workspace / "tool.md").write_text("tool description")
    db_path = tmp_path / "data" / "search" / "mcp-tools.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(
            index_name="mcp-tools", path="tool.md", file="tool.md", workspace=workspace
        )

    with VectorStore(db_path) as store:
        assert store.list_paths() == {"tool.md"}


async def test_index_with_content(tmp_path: Path):
    db_path = tmp_path / "data" / "search" / "mcp-tools.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(
            index_name="mcp-tools",
            path="echo/echo",
            content="echo: Echoes back input",
        )

    with VectorStore(db_path) as store:
        assert store.list_paths() == {"echo/echo"}


async def test_index_with_empty_content_skips(tmp_path: Path):
    db_path = tmp_path / "data" / "search" / "mcp-tools.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(
            index_name="mcp-tools",
            path="echo/echo",
            content="   ",
        )

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()


async def test_index_without_content_or_file_skips(tmp_path: Path):
    db_path = tmp_path / "data" / "search" / "workspace.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(index_name="workspace", path="something")

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()


async def test_deindex_deletes_entry(workspace: Path, tmp_path: Path):
    (workspace / "gone.md").write_text("bye")
    db_path = tmp_path / "data" / "search" / "workspace.db"

    with (
        patch("docketeer_search.tasks.Embedder", FakeEmbedder),
        patch("docketeer_search.tasks._db_path", return_value=db_path),
    ):
        await index(
            index_name="workspace", path="gone.md", file="gone.md", workspace=workspace
        )
        await deindex(index_name="workspace", path="gone.md")

    with VectorStore(db_path) as store:
        assert store.list_paths() == set()
