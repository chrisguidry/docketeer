"""Tests for file operation tools (list, read, write, delete, search, links)."""

import os
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest

from docketeer.hooks import HookResult, hook_registry
from docketeer.testing import MemoryCatalog
from docketeer.tools import ToolContext, registry


async def test_list_files(tool_context: ToolContext):
    (tool_context.workspace / "hello.txt").write_text("hi")
    (tool_context.workspace / "subdir").mkdir()
    result = await registry.execute("list_files", {"path": ""}, tool_context)
    assert "hello.txt" in result
    assert "subdir/" in result


async def test_list_files_empty_dir(tool_context: ToolContext):
    (tool_context.workspace / "empty").mkdir()
    result = await registry.execute("list_files", {"path": "empty"}, tool_context)
    assert result == "(empty directory)"


async def test_list_files_not_found(tool_context: ToolContext):
    result = await registry.execute("list_files", {"path": "nope"}, tool_context)
    assert "Directory not found" in result


async def test_list_files_not_a_dir(tool_context: ToolContext):
    (tool_context.workspace / "file.txt").write_text("hi")
    result = await registry.execute("list_files", {"path": "file.txt"}, tool_context)
    assert "Not a directory" in result


async def test_list_files_shows_symlinks(tool_context: ToolContext):
    target = tool_context.workspace / "real"
    target.mkdir()
    (tool_context.workspace / "link").symlink_to("real")
    result = await registry.execute("list_files", {"path": ""}, tool_context)
    assert "link -> real" in result


async def test_read_file(tool_context: ToolContext):
    (tool_context.workspace / "test.txt").write_text("hello world")
    result = await registry.execute("read_file", {"path": "test.txt"}, tool_context)
    assert result == "hello world"


async def test_read_file_not_found(tool_context: ToolContext):
    result = await registry.execute("read_file", {"path": "nope.txt"}, tool_context)
    assert "File not found" in result


async def test_read_file_is_dir(tool_context: ToolContext):
    (tool_context.workspace / "dir").mkdir()
    result = await registry.execute("read_file", {"path": "dir"}, tool_context)
    assert "directory" in result


async def test_read_file_binary(tool_context: ToolContext):
    (tool_context.workspace / "bin.dat").write_bytes(b"\x00\x01\x02\xff\xfe")
    result = await registry.execute("read_file", {"path": "bin.dat"}, tool_context)
    assert "Cannot read binary" in result


async def test_write_file(tool_context: ToolContext):
    result = await registry.execute(
        "write_file", {"path": "sub/new.txt", "content": "data"}, tool_context
    )
    assert "Wrote" in result
    assert (tool_context.workspace / "sub" / "new.txt").read_text() == "data"


async def test_delete_file(tool_context: ToolContext):
    (tool_context.workspace / "bye.txt").write_text("gone")
    result = await registry.execute("delete_file", {"path": "bye.txt"}, tool_context)
    assert "Deleted" in result
    assert not (tool_context.workspace / "bye.txt").exists()


async def test_delete_file_not_found(tool_context: ToolContext):
    result = await registry.execute("delete_file", {"path": "nope.txt"}, tool_context)
    assert "File not found" in result


async def test_delete_file_is_dir(tool_context: ToolContext):
    (tool_context.workspace / "dir").mkdir()
    result = await registry.execute("delete_file", {"path": "dir"}, tool_context)
    assert "Cannot delete directories" in result


async def test_create_link(tool_context: ToolContext):
    (tool_context.workspace / "real").mkdir()
    result = await registry.execute(
        "create_link", {"path": "alias", "target": "real"}, tool_context
    )
    assert "Created link" in result
    link = tool_context.workspace / "alias"
    assert link.is_symlink()
    assert os.readlink(link) == "real"


async def test_create_link_nested(tool_context: ToolContext):
    (tool_context.workspace / "people" / "chris").mkdir(parents=True)
    result = await registry.execute(
        "create_link",
        {"path": "people/peps", "target": "people/chris"},
        tool_context,
    )
    assert "Created link" in result
    link = tool_context.workspace / "people" / "peps"
    assert link.is_symlink()
    assert os.readlink(link) == "chris"


async def test_create_link_target_missing(tool_context: ToolContext):
    result = await registry.execute(
        "create_link", {"path": "alias", "target": "nonexistent"}, tool_context
    )
    assert "Target does not exist" in result


async def test_create_link_already_exists(tool_context: ToolContext):
    (tool_context.workspace / "existing").mkdir()
    (tool_context.workspace / "target").mkdir()
    result = await registry.execute(
        "create_link", {"path": "existing", "target": "target"}, tool_context
    )
    assert "Path already exists" in result


async def test_read_link(tool_context: ToolContext):
    (tool_context.workspace / "real").mkdir()
    (tool_context.workspace / "alias").symlink_to("real")
    result = await registry.execute("read_link", {"path": "alias"}, tool_context)
    assert result == "real"


async def test_read_link_not_a_symlink(tool_context: ToolContext):
    (tool_context.workspace / "regular").mkdir()
    result = await registry.execute("read_link", {"path": "regular"}, tool_context)
    assert "Not a symlink" in result


async def test_edit_file(tool_context: ToolContext):
    (tool_context.workspace / "doc.txt").write_text("hello world")
    result = await registry.execute(
        "edit_file",
        {"path": "doc.txt", "old_string": "hello", "new_string": "goodbye"},
        tool_context,
    )
    assert "Edited" in result
    assert (tool_context.workspace / "doc.txt").read_text() == "goodbye world"


async def test_edit_file_deletion(tool_context: ToolContext):
    (tool_context.workspace / "doc.txt").write_text("hello cruel world")
    result = await registry.execute(
        "edit_file",
        {"path": "doc.txt", "old_string": "cruel ", "new_string": ""},
        tool_context,
    )
    assert "Edited" in result
    assert (tool_context.workspace / "doc.txt").read_text() == "hello world"


async def test_edit_file_not_found(tool_context: ToolContext):
    result = await registry.execute(
        "edit_file",
        {"path": "nope.txt", "old_string": "x", "new_string": "y"},
        tool_context,
    )
    assert "File not found" in result


async def test_edit_file_no_match(tool_context: ToolContext):
    (tool_context.workspace / "doc.txt").write_text("hello world")
    result = await registry.execute(
        "edit_file",
        {"path": "doc.txt", "old_string": "xyz", "new_string": "abc"},
        tool_context,
    )
    assert "not found in" in result


async def test_edit_file_multiple_matches(tool_context: ToolContext):
    (tool_context.workspace / "doc.txt").write_text("aaa bbb aaa")
    result = await registry.execute(
        "edit_file",
        {"path": "doc.txt", "old_string": "aaa", "new_string": "ccc"},
        tool_context,
    )
    assert "2 times" in result


async def test_edit_file_empty_old_string(tool_context: ToolContext):
    (tool_context.workspace / "doc.txt").write_text("hello")
    result = await registry.execute(
        "edit_file",
        {"path": "doc.txt", "old_string": "", "new_string": "x"},
        tool_context,
    )
    assert "old_string must not be empty" in result


async def test_search_files(tool_context: ToolContext):
    (tool_context.workspace / "a.txt").write_text("hello world\ngoodbye world")
    (tool_context.workspace / "b.txt").write_text("nothing here")
    result = await registry.execute("search_files", {"query": "hello"}, tool_context)
    assert "a.txt:1:hello world" in result


async def test_search_files_with_subdirs(tool_context: ToolContext):
    sub = tool_context.workspace / "sub"
    sub.mkdir()
    (sub / "inner.txt").write_text("hello inside")
    result = await registry.execute("search_files", {"query": "hello"}, tool_context)
    assert "inner.txt" in result


async def test_search_files_no_matches(tool_context: ToolContext):
    (tool_context.workspace / "a.txt").write_text("nothing")
    result = await registry.execute("search_files", {"query": "xyz"}, tool_context)
    assert "No matches" in result


async def test_search_files_dir_not_found(tool_context: ToolContext):
    result = await registry.execute(
        "search_files", {"query": "x", "path": "nope"}, tool_context
    )
    assert "Directory not found" in result


async def test_search_files_max_results(tool_context: ToolContext):
    lines = "\n".join(f"match line {i}" for i in range(60))
    (tool_context.workspace / "big.txt").write_text(lines)
    result = await registry.execute("search_files", {"query": "match"}, tool_context)
    assert result.endswith("(results truncated at 50 matches)")


async def test_search_files_skips_binary(tool_context: ToolContext):
    (tool_context.workspace / "bin.dat").write_bytes(b"\x00\x01match\xff")
    (tool_context.workspace / "ok.txt").write_text("match here")
    result = await registry.execute("search_files", {"query": "match"}, tool_context)
    assert "ok.txt" in result
    assert "bin.dat" not in result


# --- semantic search path ---


async def test_search_files_semantic(workspace: Path):
    catalog = MemoryCatalog()
    await catalog.get_index("workspace").index("notes/hello.md", "hello world")
    ctx = ToolContext(workspace=workspace, search=catalog)

    result = await registry.execute("search_files", {"query": "hello"}, ctx)
    assert "1 result(s)" in result
    assert "notes/hello.md" in result


async def test_search_files_semantic_with_path_filter(workspace: Path):
    catalog = MemoryCatalog()
    await catalog.get_index("workspace").index("notes/a.md", "topic alpha")
    await catalog.get_index("workspace").index("docs/b.md", "topic beta")
    ctx = ToolContext(workspace=workspace, search=catalog)

    result = await registry.execute(
        "search_files", {"query": "topic", "path": "notes"}, ctx
    )
    assert "notes/a.md" in result
    assert "docs/b.md" not in result


async def test_search_files_semantic_path_filter_all_excluded(workspace: Path):
    catalog = MemoryCatalog()
    await catalog.get_index("workspace").index("docs/b.md", "topic beta")
    ctx = ToolContext(workspace=workspace, search=catalog)

    (workspace / "notes").mkdir()
    result = await registry.execute(
        "search_files", {"query": "topic", "path": "notes"}, ctx
    )
    assert "No matches" in result


async def test_search_files_semantic_no_results_falls_back(workspace: Path):
    catalog = MemoryCatalog()
    ctx = ToolContext(workspace=workspace, search=catalog)
    (workspace / "found.txt").write_text("keyword match here")

    result = await registry.execute("search_files", {"query": "keyword"}, ctx)
    assert "found.txt:1:keyword match here" in result


# --- Hook validate/commit write-back ---


class _EnrichingHook:
    """A hook that adds a key to the content on write."""

    prefix = PurePosixPath("enriched")

    async def validate(self, path: PurePosixPath, content: str) -> HookResult | None:
        return HookResult(
            message=f"Enriched {path}",
            updated_content=content + "\n# enriched",
        )

    async def commit(self, path: PurePosixPath, content: str) -> None:
        pass

    async def on_delete(self, path: PurePosixPath) -> str | None:
        return None  # pragma: no cover

    async def scan(self, workspace: Path) -> None:
        pass  # pragma: no cover


@pytest.fixture()
def _enriching_hook() -> Iterator[None]:
    hook = _EnrichingHook()
    hook_registry.register(hook)
    yield
    hook_registry._hooks.remove(hook)


@pytest.mark.usefixtures("_enriching_hook")
async def test_write_file_applies_updated_content(tool_context: ToolContext):
    result = await registry.execute(
        "write_file",
        {"path": "enriched/test.md", "content": "original"},
        tool_context,
    )
    assert result == "Enriched enriched/test.md"
    on_disk = (tool_context.workspace / "enriched" / "test.md").read_text()
    assert on_disk == "original\n# enriched"


@pytest.mark.usefixtures("_enriching_hook")
async def test_edit_file_applies_updated_content(tool_context: ToolContext):
    (tool_context.workspace / "enriched").mkdir()
    (tool_context.workspace / "enriched" / "test.md").write_text("old content")

    result = await registry.execute(
        "edit_file",
        {
            "path": "enriched/test.md",
            "old_string": "old",
            "new_string": "new",
        },
        tool_context,
    )
    assert result == "Enriched enriched/test.md"
    on_disk = (tool_context.workspace / "enriched" / "test.md").read_text()
    assert on_disk == "new content\n# enriched"
