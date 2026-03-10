"""Tests for antenna hook integration with workspace tools.

The old tune/detune/list_tunings tools are replaced by write_file/delete_file
operating on the tunings/ directory.
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.antenna import Antenna, AntennaHook
from docketeer.hooks import hook_registry
from docketeer.testing import MemoryBand
from docketeer.tools import ToolContext, registry


@pytest.fixture()
def band() -> MemoryBand:
    return MemoryBand("test-band")


@pytest.fixture()
async def antenna(tmp_path: Path, band: MemoryBand):
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        antenna = Antenna(AsyncMock(), tmp_path)
        async with antenna:
            yield antenna


@pytest.fixture(autouse=True)
def _register_hook(antenna: Antenna) -> Iterator[None]:
    hook = AntennaHook()
    hook.set_antenna(antenna)
    hook_registry.register(hook)
    yield
    hook_registry._hooks.remove(hook)


async def test_write_file_tunes(tool_context: ToolContext):
    content = "---\nband: test-band\ntopic: events\n---\nMonitor events."
    result = await registry.execute(
        "write_file",
        {"path": "tunings/github.md", "content": content},
        tool_context,
    )
    assert "Tuned 'github'" in result
    assert "test-band" in result


async def test_write_file_tune_with_filters(tool_context: ToolContext):
    content = (
        "---\nband: test-band\ntopic: events\nfilters:\n"
        "  - field: payload.action\n    op: eq\n    value: opened\n---\nBody."
    )
    result = await registry.execute(
        "write_file",
        {"path": "tunings/filtered.md", "content": content},
        tool_context,
    )
    assert "Tuned 'filtered'" in result


async def test_write_file_tune_unknown_band_reverts(tool_context: ToolContext):
    content = "---\nband: nope\ntopic: events\n---\nBody."
    result = await registry.execute(
        "write_file",
        {"path": "tunings/bad.md", "content": content},
        tool_context,
    )
    assert "Error" in result
    target = tool_context.workspace / "tunings" / "bad.md"
    assert not target.exists()


async def test_delete_file_detunes(tool_context: ToolContext, antenna: Antenna):
    content = "---\nband: test-band\ntopic: events\n---\nBody."
    await registry.execute(
        "write_file",
        {"path": "tunings/gh.md", "content": content},
        tool_context,
    )
    assert len(antenna.list_tunings()) == 1

    result = await registry.execute(
        "delete_file", {"path": "tunings/gh.md"}, tool_context
    )
    assert "Detuned 'gh'" in result
    assert len(antenna.list_tunings()) == 0


async def test_write_file_no_frontmatter_reverts(tool_context: ToolContext):
    result = await registry.execute(
        "write_file",
        {"path": "tunings/bad.md", "content": "No frontmatter"},
        tool_context,
    )
    assert "Error" in result


async def test_write_file_overwrite_with_bad_content_does_not_write(
    tool_context: ToolContext, antenna: Antenna
):
    good_content = "---\nband: test-band\ntopic: events\n---\nGood."
    await registry.execute(
        "write_file",
        {"path": "tunings/gh.md", "content": good_content},
        tool_context,
    )
    assert len(antenna.list_tunings()) == 1

    bad_content = "---\nband: nope\ntopic: events\n---\nBad band."
    result = await registry.execute(
        "write_file",
        {"path": "tunings/gh.md", "content": bad_content},
        tool_context,
    )
    assert "Error" in result
    # Original file should be untouched since validation happens before write
    on_disk = (tool_context.workspace / "tunings" / "gh.md").read_text()
    assert on_disk == good_content


async def test_edit_file_hook_error_preserves_original(
    tool_context: ToolContext, antenna: Antenna
):
    content = "---\nband: test-band\ntopic: events\n---\nBody."
    await registry.execute(
        "write_file",
        {"path": "tunings/gh.md", "content": content},
        tool_context,
    )

    result = await registry.execute(
        "edit_file",
        {
            "path": "tunings/gh.md",
            "old_string": "band: test-band",
            "new_string": "band: nonexistent",
        },
        tool_context,
    )
    assert "Error" in result
    # Original file should be untouched since validation happens before write
    on_disk = (tool_context.workspace / "tunings" / "gh.md").read_text()
    assert "band: test-band" in on_disk


async def test_write_non_md_passes_through(tool_context: ToolContext):
    result = await registry.execute(
        "write_file",
        {"path": "tunings/notes.txt", "content": "just a note"},
        tool_context,
    )
    assert "Wrote" in result
    assert (
        tool_context.workspace / "tunings" / "notes.txt"
    ).read_text() == "just a note"


async def test_delete_non_md_passes_through(tool_context: ToolContext):
    (tool_context.workspace / "tunings").mkdir(parents=True, exist_ok=True)
    (tool_context.workspace / "tunings" / "notes.txt").write_text("bye")
    result = await registry.execute(
        "delete_file", {"path": "tunings/notes.txt"}, tool_context
    )
    assert "Deleted" in result


async def test_edit_file_retunes(tool_context: ToolContext, antenna: Antenna):
    content = "---\nband: test-band\ntopic: old-events\n---\nBody."
    await registry.execute(
        "write_file",
        {"path": "tunings/gh.md", "content": content},
        tool_context,
    )
    assert antenna.list_tunings()[0].topic == "old-events"

    result = await registry.execute(
        "edit_file",
        {
            "path": "tunings/gh.md",
            "old_string": "old-events",
            "new_string": "new-events",
        },
        tool_context,
    )
    assert "Tuned 'gh'" in result
    assert antenna.list_tunings()[0].topic == "new-events"
