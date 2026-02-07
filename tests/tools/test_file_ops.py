"""Tests for file operation tools (list, read, write, delete, search)."""

from unittest.mock import MagicMock

from docketeer.tools import ToolContext, registry


async def test_list_files(ctx: ToolContext):
    (ctx.workspace / "hello.txt").write_text("hi")
    (ctx.workspace / "subdir").mkdir()
    result = await registry.execute("list_files", {"path": ""}, ctx)
    assert "hello.txt" in result
    assert "subdir/" in result


async def test_list_files_empty_dir(ctx: ToolContext):
    (ctx.workspace / "empty").mkdir()
    result = await registry.execute("list_files", {"path": "empty"}, ctx)
    assert result == "(empty directory)"


async def test_list_files_not_found(ctx: ToolContext):
    result = await registry.execute("list_files", {"path": "nope"}, ctx)
    assert "Directory not found" in result


async def test_list_files_not_a_dir(ctx: ToolContext):
    (ctx.workspace / "file.txt").write_text("hi")
    result = await registry.execute("list_files", {"path": "file.txt"}, ctx)
    assert "Not a directory" in result


async def test_read_file(ctx: ToolContext):
    (ctx.workspace / "test.txt").write_text("hello world")
    result = await registry.execute("read_file", {"path": "test.txt"}, ctx)
    assert result == "hello world"


async def test_read_file_not_found(ctx: ToolContext):
    result = await registry.execute("read_file", {"path": "nope.txt"}, ctx)
    assert "File not found" in result


async def test_read_file_is_dir(ctx: ToolContext):
    (ctx.workspace / "dir").mkdir()
    result = await registry.execute("read_file", {"path": "dir"}, ctx)
    assert "directory" in result


async def test_read_file_binary(ctx: ToolContext):
    (ctx.workspace / "bin.dat").write_bytes(b"\x00\x01\x02\xff\xfe")
    result = await registry.execute("read_file", {"path": "bin.dat"}, ctx)
    assert "Cannot read binary" in result


async def test_write_file(ctx: ToolContext):
    result = await registry.execute(
        "write_file", {"path": "sub/new.txt", "content": "data"}, ctx
    )
    assert "Wrote" in result
    assert (ctx.workspace / "sub" / "new.txt").read_text() == "data"


async def test_write_file_people_callback(ctx: ToolContext):
    callback = MagicMock()
    ctx.on_people_write = callback
    await registry.execute(
        "write_file",
        {"path": "people/chris/profile.md", "content": "# Chris"},
        ctx,
    )
    callback.assert_called_once()


async def test_write_file_no_callback(ctx: ToolContext):
    ctx.on_people_write = None
    result = await registry.execute(
        "write_file",
        {"path": "people/chris/profile.md", "content": "# Chris"},
        ctx,
    )
    assert "Wrote" in result


async def test_delete_file(ctx: ToolContext):
    (ctx.workspace / "bye.txt").write_text("gone")
    result = await registry.execute("delete_file", {"path": "bye.txt"}, ctx)
    assert "Deleted" in result
    assert not (ctx.workspace / "bye.txt").exists()


async def test_delete_file_not_found(ctx: ToolContext):
    result = await registry.execute("delete_file", {"path": "nope.txt"}, ctx)
    assert "File not found" in result


async def test_delete_file_is_dir(ctx: ToolContext):
    (ctx.workspace / "dir").mkdir()
    result = await registry.execute("delete_file", {"path": "dir"}, ctx)
    assert "Cannot delete directories" in result


async def test_search_files(ctx: ToolContext):
    (ctx.workspace / "a.txt").write_text("hello world\ngoodbye world")
    (ctx.workspace / "b.txt").write_text("nothing here")
    result = await registry.execute("search_files", {"query": "hello"}, ctx)
    assert "a.txt:1:hello world" in result


async def test_search_files_with_subdirs(ctx: ToolContext):
    sub = ctx.workspace / "sub"
    sub.mkdir()
    (sub / "inner.txt").write_text("hello inside")
    result = await registry.execute("search_files", {"query": "hello"}, ctx)
    assert "inner.txt" in result


async def test_search_files_no_matches(ctx: ToolContext):
    (ctx.workspace / "a.txt").write_text("nothing")
    result = await registry.execute("search_files", {"query": "xyz"}, ctx)
    assert "No matches" in result


async def test_search_files_dir_not_found(ctx: ToolContext):
    result = await registry.execute("search_files", {"query": "x", "path": "nope"}, ctx)
    assert "Directory not found" in result


async def test_search_files_max_results(ctx: ToolContext):
    lines = "\n".join(f"match line {i}" for i in range(60))
    (ctx.workspace / "big.txt").write_text(lines)
    result = await registry.execute("search_files", {"query": "match"}, ctx)
    assert result.count("\n") == 49  # 50 lines, 49 newlines


async def test_search_files_skips_binary(ctx: ToolContext):
    (ctx.workspace / "bin.dat").write_bytes(b"\x00\x01match\xff")
    (ctx.workspace / "ok.txt").write_text("match here")
    result = await registry.execute("search_files", {"query": "match"}, ctx)
    assert "ok.txt" in result
    assert "bin.dat" not in result
