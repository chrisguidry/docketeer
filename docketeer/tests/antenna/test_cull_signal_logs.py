"""Tests for signal log retention (cull_signal_logs)."""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from docketeer.signal_loop import (
    _retention_days_for_tuning,
    cull_signal_logs,
)


def _make_workspace_with_logs(
    tmp_path: Path,
    tuning_name: str,
    dates: list[str],
    frontmatter: str | None = None,
) -> Path:
    workspace = tmp_path / "workspace"
    tunings_dir = workspace / "tunings"
    log_dir = tunings_dir / tuning_name
    log_dir.mkdir(parents=True, exist_ok=True)

    for d in dates:
        (log_dir / f"{d}.jsonl").write_text(f'{{"date": "{d}"}}\n')

    if frontmatter is not None:
        (tunings_dir / f"{tuning_name}.md").write_text(frontmatter)

    return workspace


async def test_cull_deletes_old_files(tmp_path: Path):
    workspace = _make_workspace_with_logs(
        tmp_path,
        "github",
        ["2026-01-01", "2026-03-10", "2026-03-11"],
        "---\nband: wicket\ntopic: events\n---\n",
    )

    with patch("docketeer.signal_loop.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 11)
        mock_date.fromisoformat = date.fromisoformat
        await cull_signal_logs(workspace=workspace)

    log_dir = workspace / "tunings" / "github"
    assert not (log_dir / "2026-01-01.jsonl").exists()
    assert (log_dir / "2026-03-10.jsonl").exists()
    assert (log_dir / "2026-03-11.jsonl").exists()


async def test_cull_respects_retention_days(tmp_path: Path):
    workspace = _make_workspace_with_logs(
        tmp_path,
        "mail",
        ["2026-02-01", "2026-03-10"],
        "---\nband: imap\ntopic: INBOX\nretention_days: 30\n---\n",
    )

    with patch("docketeer.signal_loop.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 11)
        mock_date.fromisoformat = date.fromisoformat
        await cull_signal_logs(workspace=workspace)

    log_dir = workspace / "tunings" / "mail"
    assert not (log_dir / "2026-02-01.jsonl").exists()
    assert (log_dir / "2026-03-10.jsonl").exists()


async def test_cull_leaves_recent_files(tmp_path: Path):
    workspace = _make_workspace_with_logs(
        tmp_path,
        "t",
        ["2026-03-10", "2026-03-11"],
        "---\nband: b\ntopic: x\n---\n",
    )

    with patch("docketeer.signal_loop.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 11)
        mock_date.fromisoformat = date.fromisoformat
        await cull_signal_logs(workspace=workspace)

    log_dir = workspace / "tunings" / "t"
    assert (log_dir / "2026-03-10.jsonl").exists()
    assert (log_dir / "2026-03-11.jsonl").exists()


async def test_cull_no_md_uses_default_retention(tmp_path: Path):
    workspace = _make_workspace_with_logs(
        tmp_path,
        "orphan",
        ["2026-01-01", "2026-03-11"],
    )

    with patch("docketeer.signal_loop.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 11)
        mock_date.fromisoformat = date.fromisoformat
        await cull_signal_logs(workspace=workspace)

    log_dir = workspace / "tunings" / "orphan"
    assert not (log_dir / "2026-01-01.jsonl").exists()
    assert (log_dir / "2026-03-11.jsonl").exists()


async def test_cull_empty_tuning_dir(tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / "tunings" / "empty").mkdir(parents=True)

    await cull_signal_logs(workspace=workspace)


async def test_cull_no_tunings_dir(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    await cull_signal_logs(workspace=workspace)


async def test_cull_skips_non_date_jsonl(tmp_path: Path):
    workspace = _make_workspace_with_logs(
        tmp_path,
        "t",
        ["2026-01-01"],
        "---\nband: b\ntopic: x\n---\n",
    )
    (workspace / "tunings" / "t" / "not-a-date.jsonl").write_text("{}\n")

    with patch("docketeer.signal_loop.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 11)
        mock_date.fromisoformat = date.fromisoformat
        await cull_signal_logs(workspace=workspace)

    assert (workspace / "tunings" / "t" / "not-a-date.jsonl").exists()
    assert not (workspace / "tunings" / "t" / "2026-01-01.jsonl").exists()


def test_retention_days_for_tuning_with_frontmatter(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tunings_dir = workspace / "tunings"
    tunings_dir.mkdir(parents=True)
    (tunings_dir / "mail.md").write_text(
        "---\nband: imap\ntopic: INBOX\nretention_days: 14\n---\n"
    )
    assert _retention_days_for_tuning(workspace, "mail") == 14


def test_retention_days_for_tuning_default(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tunings_dir = workspace / "tunings"
    tunings_dir.mkdir(parents=True)
    (tunings_dir / "t.md").write_text("---\nband: b\ntopic: x\n---\n")
    assert _retention_days_for_tuning(workspace, "t") == 7


def test_retention_days_for_missing_md(tmp_path: Path):
    workspace = tmp_path / "workspace"
    (workspace / "tunings").mkdir(parents=True)
    assert _retention_days_for_tuning(workspace, "nonexistent") == 7
