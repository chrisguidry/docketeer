"""Tests for the search index protocol, NullSearch, NullCatalog, and discovery."""

from unittest.mock import MagicMock, patch

from docketeer.search import NullCatalog, NullSearch, discover_search


async def test_null_search_returns_empty_results():
    search = NullSearch()
    results = await search.search("anything")
    assert results == []


async def test_null_search_index_file_is_noop():
    search = NullSearch()
    await search.index_file("test.txt", "content")


async def test_null_search_remove_file_is_noop():
    search = NullSearch()
    await search.remove_file("test.txt")


def test_null_catalog_returns_null_search():
    catalog = NullCatalog()
    index = catalog.get_index("workspace")
    assert isinstance(index, NullSearch)


def test_null_catalog_returns_fresh_null_search_each_time():
    catalog = NullCatalog()
    a = catalog.get_index("workspace")
    b = catalog.get_index("workspace")
    assert isinstance(a, NullSearch)
    assert isinstance(b, NullSearch)


def test_discover_search_returns_null_catalog_when_no_plugin():
    with patch("docketeer.search.discover_one", return_value=None):
        search = discover_search()
    assert isinstance(search, NullCatalog)


def test_discover_search_returns_plugin_catalog():
    fake_catalog = NullCatalog()
    module = MagicMock()
    module.create_search.return_value = fake_catalog

    ep = MagicMock()
    ep.load.return_value = module

    with patch("docketeer.search.discover_one", return_value=ep):
        result = discover_search(docket="fake-docket")

    module.create_search.assert_called_once_with(docket="fake-docket")
    assert result is fake_catalog
