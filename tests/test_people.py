"""Tests for person profile loading and matching."""

from datetime import datetime, timedelta
from pathlib import Path

from docketeer.people import build_person_map, load_person_context


def test_build_person_map_no_dir(tmp_path: Path):
    assert build_person_map(tmp_path) == {}


def test_build_person_map_empty_dir(tmp_path: Path):
    (tmp_path / "people").mkdir()
    assert build_person_map(tmp_path) == {}


def test_build_person_map_finds_usernames(tmp_path: Path):
    people = tmp_path / "people"
    chris = people / "chris"
    chris.mkdir(parents=True)
    (chris / "profile.md").write_text("# Chris\n**Username:** @cguidry\nLikes coffee")

    alex = people / "alex"
    alex.mkdir()
    (alex / "profile.md").write_text("**Username:** @alex123\n")

    result = build_person_map(tmp_path)
    assert result == {"cguidry": "people/chris", "alex123": "people/alex"}


def test_build_person_map_skips_missing_username(tmp_path: Path):
    people = tmp_path / "people"
    noname = people / "noname"
    noname.mkdir(parents=True)
    (noname / "profile.md").write_text("# No username here\nJust a profile")

    assert build_person_map(tmp_path) == {}


def test_load_person_context_unknown_user(tmp_path: Path):
    assert load_person_context(tmp_path, "nobody", {}) == ""


def test_load_person_context_profile_only(tmp_path: Path):
    people = tmp_path / "people" / "chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("# Chris\n**Username:** @cguidry")

    result = load_person_context(tmp_path, "cguidry", {"cguidry": "people/chris"})
    assert "# Chris" in result
    assert "**Username:** @cguidry" in result


def test_load_person_context_with_journal_mentions(tmp_path: Path):
    people = tmp_path / "people" / "chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("**Username:** @cguidry")

    journal = tmp_path / "journal"
    journal.mkdir()
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    (journal / f"{today}.md").write_text(
        f"# {today}\n\n"
        "- 10:00 | talked to [[people/chris]] about testing\n"
        "- 11:00 | did some cleanup\n"
    )

    result = load_person_context(tmp_path, "cguidry", {"cguidry": "people/chris"})
    assert "[[people/chris]]" in result
    assert "Recent journal mentions" in result
    assert "did some cleanup" not in result


def test_load_person_context_journal_date_cutoff(tmp_path: Path):
    people = tmp_path / "people" / "chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("**Username:** @cguidry")

    journal = tmp_path / "journal"
    journal.mkdir()

    old_date = (datetime.now().astimezone() - timedelta(days=10)).strftime("%Y-%m-%d")
    (journal / f"{old_date}.md").write_text(
        f"# {old_date}\n\n- 10:00 | talked to [[people/chris]] long ago\n"
    )

    result = load_person_context(tmp_path, "cguidry", {"cguidry": "people/chris"})
    assert "long ago" not in result


def test_load_person_context_no_profile_file(tmp_path: Path):
    """Person is in the map but profile.md doesn't exist."""
    (tmp_path / "people" / "ghost").mkdir(parents=True)
    result = load_person_context(tmp_path, "ghost", {"ghost": "people/ghost"})
    assert result == ""


def test_load_person_context_case_insensitive_wikilink(tmp_path: Path):
    people = tmp_path / "people" / "Chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("**Username:** @cguidry")

    journal = tmp_path / "journal"
    journal.mkdir()
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    (journal / f"{today}.md").write_text(
        f"# {today}\n\n- 10:00 | talked to [[People/Chris]] about things\n"
    )

    result = load_person_context(tmp_path, "cguidry", {"cguidry": "people/Chris"})
    assert "about things" in result
