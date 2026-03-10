"""Tests for the scheduling hook."""

from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, MagicMock

import pytest

from docketeer.hooks import parse_frontmatter
from docketeer.tasks import SchedulingHook


@pytest.fixture()
def mock_docket() -> MagicMock:
    docket = MagicMock()
    docket.tasks = {}
    docket.replace.return_value = AsyncMock()
    docket.add.return_value = AsyncMock()
    docket.cancel = AsyncMock()
    return docket


@pytest.fixture()
def hook(mock_docket: MagicMock) -> SchedulingHook:
    h = SchedulingHook()
    h.set_docket(mock_docket)
    return h


async def test_validate_recurring_cron(hook: SchedulingHook):
    content = "---\nevery: '0 9 * * 1-5'\nline: standup\n---\nDo standup."
    result = await hook.validate(PurePosixPath("tasks/standup.md"), content)
    assert result is not None
    assert "Scheduled 'standup'" in result.message
    assert "cron" in result.message


async def test_commit_recurring_cron(hook: SchedulingHook, mock_docket: MagicMock):
    content = "---\nevery: '0 9 * * 1-5'\nline: standup\nkey: standup\n---\nDo standup."
    await hook.commit(PurePosixPath("tasks/standup.md"), content)
    mock_docket.replace.assert_called_once()


async def test_validate_recurring_duration(hook: SchedulingHook):
    content = "---\nevery: PT30M\n---\nCheck status."
    result = await hook.validate(PurePosixPath("tasks/check.md"), content)
    assert result is not None
    assert "Scheduled 'check'" in result.message
    assert "every PT30M" in result.message


async def test_commit_recurring_duration(hook: SchedulingHook, mock_docket: MagicMock):
    content = "---\nevery: PT30M\nkey: check\n---\nCheck status."
    await hook.commit(PurePosixPath("tasks/check.md"), content)
    mock_docket.replace.assert_called_once()


async def test_validate_one_shot(hook: SchedulingHook):
    content = "---\nwhen: '2026-12-25T10:00:00-05:00'\n---\nRemind Chris."
    result = await hook.validate(PurePosixPath("tasks/remind.md"), content)
    assert result is not None
    assert "Scheduled 'remind'" in result.message


async def test_commit_one_shot(hook: SchedulingHook, mock_docket: MagicMock):
    content = "---\nwhen: '2026-12-25T10:00:00-05:00'\nkey: remind\n---\nRemind Chris."
    await hook.commit(PurePosixPath("tasks/remind.md"), content)
    mock_docket.replace.assert_called_once()


async def test_validate_no_frontmatter_raises(hook: SchedulingHook):
    with pytest.raises(ValueError, match="needs YAML frontmatter"):
        await hook.validate(PurePosixPath("tasks/bad.md"), "No frontmatter here.")


async def test_validate_missing_every_and_when_raises(hook: SchedulingHook):
    content = "---\nline: foo\n---\nBody."
    with pytest.raises(ValueError, match="needs 'every'"):
        await hook.validate(PurePosixPath("tasks/bad.md"), content)


async def test_validate_invalid_cron_raises(hook: SchedulingHook):
    content = "---\nevery: not-valid\n---\nBody."
    with pytest.raises(ValueError, match="Invalid schedule expression"):
        await hook.validate(PurePosixPath("tasks/bad.md"), content)


async def test_validate_invalid_timezone_raises(hook: SchedulingHook):
    content = "---\nevery: '0 9 * * *'\ntimezone: Fake/Zone\n---\nBody."
    with pytest.raises(ValueError, match="Invalid timezone"):
        await hook.validate(PurePosixPath("tasks/bad.md"), content)


async def test_validate_invalid_datetime_raises(hook: SchedulingHook):
    content = "---\nwhen: not-a-date\n---\nBody."
    with pytest.raises(ValueError, match="Invalid datetime"):
        await hook.validate(PurePosixPath("tasks/bad.md"), content)


async def test_validate_non_md_returns_none(hook: SchedulingHook):
    result = await hook.validate(PurePosixPath("tasks/notes.txt"), "hello")
    assert result is None


async def test_commit_non_md_is_noop(hook: SchedulingHook, mock_docket: MagicMock):
    await hook.commit(PurePosixPath("tasks/notes.txt"), "hello")
    mock_docket.replace.assert_not_called()


async def test_on_delete_cancels_task(hook: SchedulingHook, mock_docket: MagicMock):
    result = await hook.on_delete(PurePosixPath("tasks/remind.md"))
    assert result is not None
    assert "Cancelled task 'remind'" in result
    mock_docket.cancel.assert_awaited_once_with("remind")


async def test_on_delete_non_md_returns_none(hook: SchedulingHook):
    result = await hook.on_delete(PurePosixPath("tasks/notes.txt"))
    assert result is None


async def test_scan_registers_valid_tasks(
    hook: SchedulingHook, mock_docket: MagicMock, workspace: Path
):
    tasks_dir = workspace / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "daily.md").write_text("---\nevery: PT1H\n---\nCheck things.")
    (tasks_dir / "plain.md").write_text("No frontmatter, skipped.")

    await hook.scan(workspace)
    mock_docket.replace.assert_called_once()


async def test_scan_no_tasks_dir(hook: SchedulingHook, workspace: Path):
    await hook.scan(workspace)


async def test_scan_skips_invalid_tasks(
    hook: SchedulingHook, mock_docket: MagicMock, workspace: Path
):
    tasks_dir = workspace / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "bad.md").write_text("---\nline: foo\n---\nNo schedule info.")

    await hook.scan(workspace)
    mock_docket.replace.assert_not_called()


async def test_validate_with_all_options(hook: SchedulingHook):
    content = (
        "---\nevery: PT30M\nline: research\nsilent: true\ntier: fast\n---\nDo research."
    )
    result = await hook.validate(PurePosixPath("tasks/research.md"), content)
    assert result is not None
    assert "Scheduled 'research'" in result.message


async def test_commit_with_all_options(hook: SchedulingHook, mock_docket: MagicMock):
    content = (
        "---\n"
        "every: PT30M\n"
        "line: research\n"
        "silent: true\n"
        "tier: fast\n"
        "key: research\n"
        "---\nDo research."
    )
    await hook.commit(PurePosixPath("tasks/research.md"), content)
    call_kwargs = mock_docket.replace.return_value.call_args[1]
    assert call_kwargs["line"] == "research"
    assert call_kwargs["tier"] == "fast"


async def test_not_wired_raises():
    hook = SchedulingHook()
    with pytest.raises(RuntimeError, match="not wired"):
        await hook.commit(
            PurePosixPath("tasks/test.md"), "---\nevery: PT1H\nkey: test\n---\nBody."
        )


async def test_validate_adds_key_to_frontmatter(hook: SchedulingHook):
    content = "---\nevery: PT30M\n---\nCheck status."
    result = await hook.validate(PurePosixPath("tasks/check.md"), content)
    assert result is not None
    assert result.updated_content is not None
    meta, body = parse_frontmatter(result.updated_content)
    assert meta["key"] == "check"
    assert body == "Check status."


async def test_validate_key_already_present_no_update(hook: SchedulingHook):
    content = "---\nevery: PT30M\nkey: check\n---\nCheck status."
    result = await hook.validate(PurePosixPath("tasks/check.md"), content)
    assert result is not None
    assert result.updated_content is None


async def test_scan_skips_invalid_timezone(
    hook: SchedulingHook, mock_docket: MagicMock, workspace: Path
):
    tasks_dir = workspace / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "bad-tz.md").write_text(
        "---\nevery: '0 9 * * *'\ntimezone: Fake/Zone\n---\nBody."
    )
    await hook.scan(workspace)
    mock_docket.replace.assert_not_called()


async def test_scan_skips_invalid_cron(
    hook: SchedulingHook, mock_docket: MagicMock, workspace: Path
):
    tasks_dir = workspace / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "bad-cron.md").write_text("---\nevery: not-valid\n---\nBody.")
    await hook.scan(workspace)
    mock_docket.replace.assert_not_called()


async def test_scan_skips_invalid_datetime(
    hook: SchedulingHook, mock_docket: MagicMock, workspace: Path
):
    tasks_dir = workspace / "tasks"
    tasks_dir.mkdir(parents=True)
    (tasks_dir / "bad-when.md").write_text("---\nwhen: not-a-date\n---\nBody.")
    await hook.scan(workspace)
    mock_docket.replace.assert_not_called()
