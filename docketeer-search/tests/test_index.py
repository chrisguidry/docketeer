"""Tests for FastembedCatalog and FastembedIndex."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer_search import tasks
from docketeer_search.index import (
    FastembedCatalog,
    FastembedIndex,
)
from tests.helpers import FakeEmbedder


@pytest.fixture()
def mock_docket() -> MagicMock:
    docket = MagicMock()
    docket.add.return_value = AsyncMock()
    return docket


@pytest.fixture()
def catalog(tmp_path: Path, mock_docket: MagicMock) -> Iterator[FastembedCatalog]:
    with (
        patch("docketeer_search.index.Embedder", FakeEmbedder),
        patch("docketeer_search.index.environment.DATA_DIR", tmp_path / "data"),
    ):
        with FastembedCatalog(docket=mock_docket) as c:
            yield c


def test_get_index_returns_fastembed_index(catalog: FastembedCatalog):
    index = catalog.get_index("workspace")
    assert isinstance(index, FastembedIndex)


def test_get_index_returns_same_instance(catalog: FastembedCatalog):
    a = catalog.get_index("workspace")
    b = catalog.get_index("workspace")
    assert a is b


def test_get_index_different_names(catalog: FastembedCatalog):
    ws = catalog.get_index("workspace")
    mcp = catalog.get_index("mcp-tools")
    assert ws is not mcp


async def test_search_empty_index(catalog: FastembedCatalog):
    index = catalog.get_index("workspace")
    results = await index.search("anything")
    assert results == []


async def test_search_finds_indexed_content(catalog: FastembedCatalog):
    index = catalog.get_index("workspace")
    vec = index._embedder.embed(["hello world"])[0]
    index._store.upsert("note.md", vec, "hello world")

    results = await index.search("hello world")
    assert len(results) == 1
    assert results[0].path == "note.md"


async def test_index_schedules_docket_task(
    catalog: FastembedCatalog, mock_docket: MagicMock
):
    index = catalog.get_index("workspace")
    await index.index("test.md", "content")
    mock_docket.add.assert_called_once_with(
        tasks.index, key="search:index:workspace:test.md"
    )


async def test_deindex_schedules_docket_task(
    catalog: FastembedCatalog, mock_docket: MagicMock
):
    index = catalog.get_index("workspace")
    await index.deindex("test.md")
    mock_docket.add.assert_called_once_with(
        tasks.deindex, key="search:remove:workspace:test.md"
    )


async def test_index_passes_index_name_and_content(
    catalog: FastembedCatalog, mock_docket: MagicMock
):
    index = catalog.get_index("mcp-tools")
    await index.index("server/tool", "description")
    mock_docket.add.assert_called_once_with(
        tasks.index, key="search:index:mcp-tools:server/tool"
    )
    schedule_fn = mock_docket.add.return_value
    schedule_fn.assert_called_once_with(
        index_name="mcp-tools", path="server/tool", content="description"
    )
