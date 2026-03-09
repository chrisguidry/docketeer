"""Tests for antenna tools — tune, detune, list_tunings, list_bands."""

from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.antenna import Antenna
from docketeer.testing import MemoryBand
from docketeer.tools import ToolContext, registry


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace)


@pytest.fixture()
def band() -> MemoryBand:
    return MemoryBand("test-band")


@pytest.fixture()
async def antenna(tmp_path: Path, band: MemoryBand) -> AsyncGenerator[Antenna]:
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        antenna = Antenna(AsyncMock(), tmp_path, tmp_path)
        await antenna.__aenter__()
        yield antenna
        await antenna.__aexit__(None, None, None)


@pytest.fixture(autouse=True)
def _register_tools(antenna: Antenna) -> Generator[None]:
    from docketeer.antenna_tools import register_antenna_tools

    register_antenna_tools(antenna)
    yield
    for name in ("tune", "detune", "list_tunings", "list_bands"):
        registry._tools.pop(name, None)


async def test_tune_creates_tuning(tool_context: ToolContext):
    result = await registry.execute(
        "tune",
        {"name": "my-tuning", "band": "test-band", "topic": "events"},
        tool_context,
    )
    assert "my-tuning" in result
    assert "test-band" in result


async def test_tune_with_filters(tool_context: ToolContext):
    result = await registry.execute(
        "tune",
        {
            "name": "filtered",
            "band": "test-band",
            "topic": "events",
            "filters": [{"path": "payload.action", "op": "eq", "value": "opened"}],
        },
        tool_context,
    )
    assert "filtered" in result


async def test_tune_with_line(tool_context: ToolContext):
    result = await registry.execute(
        "tune",
        {
            "name": "github-prs",
            "band": "test-band",
            "topic": "events",
            "line": "opensource",
        },
        tool_context,
    )
    assert "opensource" in result


async def test_tune_unknown_band(tool_context: ToolContext):
    result = await registry.execute(
        "tune",
        {"name": "bad", "band": "nope", "topic": "events"},
        tool_context,
    )
    assert "error" in result.lower()


async def test_detune_removes_tuning(tool_context: ToolContext):
    await registry.execute(
        "tune",
        {"name": "t1", "band": "test-band", "topic": "events"},
        tool_context,
    )
    result = await registry.execute("detune", {"name": "t1"}, tool_context)
    assert "t1" in result


async def test_detune_unknown(tool_context: ToolContext):
    result = await registry.execute("detune", {"name": "nope"}, tool_context)
    assert "error" in result.lower()


async def test_list_tunings_empty(tool_context: ToolContext):
    result = await registry.execute("list_tunings", {}, tool_context)
    assert "no tunings" in result.lower()


async def test_list_tunings_with_tunings(tool_context: ToolContext):
    await registry.execute(
        "tune",
        {"name": "t1", "band": "test-band", "topic": "events"},
        tool_context,
    )
    result = await registry.execute("list_tunings", {}, tool_context)
    assert "t1" in result
    assert "test-band" in result


async def test_list_bands(tool_context: ToolContext):
    result = await registry.execute("list_bands", {}, tool_context)
    assert "test-band" in result


async def test_tune_with_secrets(tool_context: ToolContext):
    result = await registry.execute(
        "tune",
        {
            "name": "secure-hook",
            "band": "test-band",
            "topic": "events",
            "secrets": {"token": "wicket/github-token"},
        },
        tool_context,
    )
    assert "secure-hook" in result


async def test_list_bands_shows_description(
    tool_context: ToolContext, antenna: Antenna
):
    antenna._bands["test-band"].description = "A test band for testing."
    result = await registry.execute("list_bands", {}, tool_context)
    assert "test-band" in result
    assert "A test band for testing." in result


async def test_list_bands_empty(tool_context: ToolContext, antenna: Antenna):
    antenna._bands.clear()
    result = await registry.execute("list_bands", {}, tool_context)
    assert "no bands" in result.lower()
