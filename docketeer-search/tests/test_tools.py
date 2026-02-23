"""Tests for the semantic_search tool."""

from pathlib import Path

from docketeer.testing import MemorySearch
from docketeer.tools import ToolContext, registry


async def test_semantic_search_returns_results(tmp_path: Path):
    search = MemorySearch()
    await search.index_file("notes/hello.md", "hello world")
    ctx = ToolContext(workspace=tmp_path, search=search)

    result = await registry.execute("semantic_search", {"query": "hello"}, ctx)
    assert "1 result(s)" in result
    assert "notes/hello.md" in result


async def test_semantic_search_no_results(tmp_path: Path):
    search = MemorySearch()
    ctx = ToolContext(workspace=tmp_path, search=search)

    result = await registry.execute("semantic_search", {"query": "nothing"}, ctx)
    assert "No results" in result


async def test_semantic_search_respects_limit(tmp_path: Path):
    search = MemorySearch()
    for i in range(5):
        await search.index_file(f"file{i}.md", "matching content")
    ctx = ToolContext(workspace=tmp_path, search=search)

    result = await registry.execute(
        "semantic_search", {"query": "matching", "limit": 2}, ctx
    )
    assert "2 result(s)" in result


async def test_semantic_search_formats_snippet(tmp_path: Path):
    search = MemorySearch()
    await search.index_file("doc.md", "line one\nline two\nline three")
    ctx = ToolContext(workspace=tmp_path, search=search)

    result = await registry.execute("semantic_search", {"query": "line"}, ctx)
    assert "line one line two" in result


async def test_semantic_search_null_search(tmp_path: Path):
    ctx = ToolContext(workspace=tmp_path)

    result = await registry.execute("semantic_search", {"query": "test"}, ctx)
    assert "No results" in result
