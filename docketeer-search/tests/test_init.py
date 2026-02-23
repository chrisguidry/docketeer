"""Tests for the plugin entry point."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from docketeer_search import create_search, task_collections
from docketeer_search.index import FastembedSearch
from tests.conftest import FakeEmbedder


def test_create_search(tmp_path: Path):
    docket = AsyncMock()
    with (
        patch("docketeer_search.index.Embedder", FakeEmbedder),
        patch("docketeer_search.index.environment.DATA_DIR", tmp_path / "data"),
    ):
        with create_search(docket=docket) as search:
            assert isinstance(search, FastembedSearch)


def test_task_collections():
    assert "docketeer_search.tasks:search_tasks" in task_collections
