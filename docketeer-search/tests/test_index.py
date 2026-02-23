"""Tests for FastembedSearch."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer_search.index import INDEX_TASK, REMOVE_TASK, FastembedSearch
from tests.conftest import FakeEmbedder


@pytest.fixture()
def mock_docket() -> MagicMock:
    docket = MagicMock()
    docket.add.return_value = AsyncMock()
    return docket


@pytest.fixture()
def search(tmp_path: Path, mock_docket: MagicMock) -> Iterator[FastembedSearch]:
    with (
        patch("docketeer_search.index.Embedder", FakeEmbedder),
        patch("docketeer_search.index.environment.DATA_DIR", tmp_path / "data"),
    ):
        with FastembedSearch(docket=mock_docket) as s:  # type: ignore[arg-type]
            yield s


async def test_search_empty_index(search: FastembedSearch):
    results = await search.search("anything")
    assert results == []


async def test_search_finds_indexed_content(search: FastembedSearch):
    vec = search._embedder.embed(["hello world"])[0]
    search._store.upsert("note.md", vec, "hello world")

    results = await search.search("hello world")
    assert len(results) == 1
    assert results[0].path == "note.md"


async def test_index_file_schedules_docket_task(
    search: FastembedSearch, mock_docket: MagicMock
):
    await search.index_file("test.md", "content")
    mock_docket.add.assert_called_once_with(INDEX_TASK, key="search:index:test.md")


async def test_remove_file_schedules_docket_task(
    search: FastembedSearch, mock_docket: MagicMock
):
    await search.remove_file("test.md")
    mock_docket.add.assert_called_once_with(REMOVE_TASK, key="search:remove:test.md")
