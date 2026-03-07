"""Tests for line context loading."""

from datetime import datetime, timedelta
from pathlib import Path

from docketeer_autonomy.lines import load_line_context


def test_load_line_context_no_lines_dir(tmp_path: Path):
    assert load_line_context(tmp_path, "general") == ""


def test_load_line_context_no_line_file(tmp_path: Path):
    (tmp_path / "lines").mkdir()
    assert load_line_context(tmp_path, "general") == ""


def test_load_line_context_line_file_exists(tmp_path: Path):
    lines = tmp_path / "lines"
    lines.mkdir()
    (lines / "general.md").write_text("# General\nThe main channel")

    result = load_line_context(tmp_path, "general")
    assert "# General" in result
    assert "The main channel" in result


def test_load_line_context_with_journal_mentions(tmp_path: Path):
    lines = tmp_path / "lines"
    lines.mkdir()
    (lines / "general.md").write_text("# General")

    journal = tmp_path / "journal"
    journal.mkdir()
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    (journal / f"{today}.md").write_text(
        f"# {today}\n\n"
        "- 10:00 | discussed plans in [[lines/general]]\n"
        "- 11:00 | unrelated entry\n"
    )

    result = load_line_context(tmp_path, "general")
    assert "[[lines/general]]" in result
    assert "Recent journal mentions" in result
    assert "unrelated entry" not in result


def test_load_line_context_journal_date_cutoff(tmp_path: Path):
    lines = tmp_path / "lines"
    lines.mkdir()
    (lines / "general.md").write_text("# General")

    journal = tmp_path / "journal"
    journal.mkdir()
    old_date = (datetime.now().astimezone() - timedelta(days=10)).strftime("%Y-%m-%d")
    (journal / f"{old_date}.md").write_text(
        f"# {old_date}\n\n- 10:00 | old mention in [[lines/general]]\n"
    )

    result = load_line_context(tmp_path, "general")
    assert "old mention" not in result


def test_load_line_context_case_insensitive_wikilink(tmp_path: Path):
    lines = tmp_path / "lines"
    lines.mkdir()
    (lines / "General.md").write_text("# General")

    journal = tmp_path / "journal"
    journal.mkdir()
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    (journal / f"{today}.md").write_text(
        f"# {today}\n\n- 10:00 | talked in [[Lines/General]]\n"
    )

    result = load_line_context(tmp_path, "General")
    assert "talked in" in result
