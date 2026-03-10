"""Tests for the antenna hook."""

from collections.abc import AsyncGenerator
from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.antenna import Antenna, AntennaHook
from docketeer.testing import MemoryBand


@pytest.fixture()
def band() -> MemoryBand:
    return MemoryBand(name="wicket")


@pytest.fixture()
async def antenna(band: MemoryBand, workspace: Path) -> AsyncGenerator[Antenna]:
    with patch("docketeer.antenna.discover_bands", return_value={"wicket": band}):
        a = Antenna(AsyncMock(), workspace)
        async with a:
            yield a


@pytest.fixture()
def hook(antenna: Antenna) -> AntennaHook:
    h = AntennaHook()
    h.set_antenna(antenna)
    return h


async def test_validate_creates_tuning_message(hook: AntennaHook):
    content = (
        "---\nband: wicket\ntopic: https://example.com/events\n---\nMonitor events."
    )
    result = await hook.validate(PurePosixPath("tunings/github.md"), content)
    assert result is not None
    assert "Tuned 'github'" in result.message
    assert "wicket" in result.message


async def test_commit_activates_tuning(hook: AntennaHook, antenna: Antenna):
    content = (
        "---\nband: wicket\ntopic: https://example.com/events\n---\nMonitor events."
    )
    await hook.commit(PurePosixPath("tunings/github.md"), content)
    assert len(antenna.list_tunings()) == 1


async def test_validate_with_filters(hook: AntennaHook):
    content = (
        "---\n"
        "band: wicket\n"
        "topic: events\n"
        "filters:\n"
        "  - field: payload.action\n"
        "    op: eq\n"
        "    value: push\n"
        "---\nBody."
    )
    result = await hook.validate(PurePosixPath("tunings/filtered.md"), content)
    assert result is not None
    assert "Tuned 'filtered'" in result.message


async def test_commit_with_filters(hook: AntennaHook, antenna: Antenna):
    content = (
        "---\n"
        "band: wicket\n"
        "topic: events\n"
        "filters:\n"
        "  - field: payload.action\n"
        "    op: eq\n"
        "    value: push\n"
        "---\nBody."
    )
    await hook.commit(PurePosixPath("tunings/filtered.md"), content)
    tuning = antenna.list_tunings()[0]
    assert len(tuning.filters) == 1
    assert tuning.filters[0].path == "payload.action"


async def test_validate_with_line(hook: AntennaHook):
    content = "---\nband: wicket\ntopic: events\nline: opensource\n---\nBody."
    result = await hook.validate(PurePosixPath("tunings/gh.md"), content)
    assert result is not None
    assert "opensource" in result.message


async def test_commit_with_line(hook: AntennaHook, antenna: Antenna):
    content = "---\nband: wicket\ntopic: events\nline: opensource\n---\nBody."
    await hook.commit(PurePosixPath("tunings/gh.md"), content)
    tuning = antenna.list_tunings()[0]
    assert tuning.line == "opensource"


async def test_validate_with_secrets(hook: AntennaHook):
    content = (
        "---\n"
        "band: wicket\n"
        "topic: events\n"
        "secrets:\n"
        "  token: vault/github-token\n"
        "---\nBody."
    )
    result = await hook.validate(PurePosixPath("tunings/gh.md"), content)
    assert result is not None
    assert "Tuned 'gh'" in result.message


async def test_commit_with_secrets(hook: AntennaHook, antenna: Antenna):
    content = (
        "---\n"
        "band: wicket\n"
        "topic: events\n"
        "secrets:\n"
        "  token: vault/github-token\n"
        "---\nBody."
    )
    await hook.commit(PurePosixPath("tunings/gh.md"), content)
    tuning = antenna.list_tunings()[0]
    assert tuning.secrets == {"token": "vault/github-token"}


async def test_validate_no_frontmatter_raises(hook: AntennaHook):
    with pytest.raises(ValueError, match="needs YAML frontmatter"):
        await hook.validate(PurePosixPath("tunings/bad.md"), "Plain text only.")


async def test_validate_missing_band_raises(hook: AntennaHook):
    content = "---\ntopic: events\n---\nBody."
    with pytest.raises(ValueError, match="requires 'band' and 'topic'"):
        await hook.validate(PurePosixPath("tunings/bad.md"), content)


async def test_validate_missing_topic_raises(hook: AntennaHook):
    content = "---\nband: wicket\n---\nBody."
    with pytest.raises(ValueError, match="requires 'band' and 'topic'"):
        await hook.validate(PurePosixPath("tunings/bad.md"), content)


async def test_validate_unknown_band_raises(hook: AntennaHook):
    content = "---\nband: nonexistent\ntopic: events\n---\nBody."
    with pytest.raises(ValueError, match="Unknown band"):
        await hook.validate(PurePosixPath("tunings/bad.md"), content)


async def test_validate_non_md_returns_none(hook: AntennaHook):
    result = await hook.validate(PurePosixPath("tunings/notes.txt"), "hello")
    assert result is None


async def test_validate_signal_subdir_returns_none(hook: AntennaHook):
    result = await hook.validate(
        PurePosixPath("tunings/gh/signals/2026-03-10.jsonl"), "data"
    )
    assert result is None


async def test_validate_nested_md_returns_none(hook: AntennaHook):
    result = await hook.validate(PurePosixPath("tunings/gh/notes/readme.md"), "data")
    assert result is None


async def test_commit_non_md_is_noop(hook: AntennaHook, antenna: Antenna):
    await hook.commit(PurePosixPath("tunings/notes.txt"), "hello")
    assert len(antenna.list_tunings()) == 0


async def test_on_delete_detunes(hook: AntennaHook, antenna: Antenna):
    content = "---\nband: wicket\ntopic: events\n---\nBody."
    await hook.commit(PurePosixPath("tunings/gh.md"), content)
    assert len(antenna.list_tunings()) == 1

    result = await hook.on_delete(PurePosixPath("tunings/gh.md"))
    assert result is not None
    assert "Detuned 'gh'" in result
    assert len(antenna.list_tunings()) == 0


async def test_on_delete_unknown_tuning(hook: AntennaHook):
    result = await hook.on_delete(PurePosixPath("tunings/nonexistent.md"))
    assert result is not None
    assert "No tuning named" in result


async def test_on_delete_non_md_returns_none(hook: AntennaHook):
    result = await hook.on_delete(PurePosixPath("tunings/notes.txt"))
    assert result is None


async def test_on_delete_signal_subdir_returns_none(hook: AntennaHook):
    result = await hook.on_delete(PurePosixPath("tunings/gh/signals/old.jsonl"))
    assert result is None


async def test_on_delete_nested_md_returns_none(hook: AntennaHook):
    result = await hook.on_delete(PurePosixPath("tunings/gh/notes/readme.md"))
    assert result is None


async def test_scan_activates_tunings(
    hook: AntennaHook, antenna: Antenna, workspace: Path
):
    tunings_dir = workspace / "tunings"
    tunings_dir.mkdir(parents=True)
    (tunings_dir / "gh.md").write_text(
        "---\nband: wicket\ntopic: events\n---\nMonitor events."
    )
    (tunings_dir / "plain.md").write_text("No frontmatter, skipped.")

    await hook.scan(workspace)
    assert len(antenna.list_tunings()) == 1


async def test_scan_no_tunings_dir(hook: AntennaHook, workspace: Path):
    await hook.scan(workspace)


async def test_scan_skips_invalid_tunings(
    hook: AntennaHook, antenna: Antenna, workspace: Path
):
    tunings_dir = workspace / "tunings"
    tunings_dir.mkdir(parents=True)
    (tunings_dir / "bad.md").write_text("---\nband: nonexistent\ntopic: x\n---\nBody.")

    await hook.scan(workspace)
    assert len(antenna.list_tunings()) == 0


async def test_not_wired_raises():
    hook = AntennaHook()
    with pytest.raises(RuntimeError, match="not wired"):
        await hook.validate(
            PurePosixPath("tunings/test.md"),
            "---\nband: wicket\ntopic: events\n---\nBody.",
        )


async def test_replaces_existing_tuning(hook: AntennaHook, antenna: Antenna):
    content1 = "---\nband: wicket\ntopic: events1\n---\nV1."
    await hook.commit(PurePosixPath("tunings/gh.md"), content1)
    assert antenna.list_tunings()[0].topic == "events1"

    content2 = "---\nband: wicket\ntopic: events2\n---\nV2."
    await hook.commit(PurePosixPath("tunings/gh.md"), content2)
    assert len(antenna.list_tunings()) == 1
    assert antenna.list_tunings()[0].topic == "events2"


async def test_scan_skips_missing_band_or_topic(
    hook: AntennaHook, antenna: Antenna, workspace: Path
):
    tunings_dir = workspace / "tunings"
    tunings_dir.mkdir(parents=True)
    (tunings_dir / "no-topic.md").write_text("---\nband: wicket\n---\nBody.")
    (tunings_dir / "no-band.md").write_text("---\ntopic: events\n---\nBody.")

    await hook.scan(workspace)
    assert len(antenna.list_tunings()) == 0


async def test_parse_filters_skips_non_dict(hook: AntennaHook, antenna: Antenna):
    content = (
        "---\nband: wicket\ntopic: events\nfilters:\n"
        "  - not-a-dict\n"
        "  - field: payload.x\n    op: eq\n    value: y\n---\nBody."
    )
    await hook.commit(PurePosixPath("tunings/gh.md"), content)
    tuning = antenna.list_tunings()[0]
    assert len(tuning.filters) == 1
