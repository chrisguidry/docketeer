"""Tests for file operation tools (list, read, write, delete, search)."""

from unittest.mock import MagicMock

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


async def test_write_file_people_callback(tool_context: ToolContext):
    callback = MagicMock()
    tool_context.on_people_write = callback
    await registry.execute(
        "write_file",
        {"path": "people/chris/profile.md", "content": "# Chris"},
        tool_context,
    )
    callback.assert_called_once()


async def test_write_file_no_callback(tool_context: ToolContext):
    tool_context.on_people_write = None
    result = await registry.execute(
        "write_file",
        {"path": "people/chris/profile.md", "content": "# Chris"},
        tool_context,
    )
    assert "Wrote" in result


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
