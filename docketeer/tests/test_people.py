"""Tests for person profile loading."""

from datetime import datetime, timedelta
from pathlib import Path

from docketeer.people import load_person_context


def test_load_person_context_unknown_user(tmp_path: Path):
    assert load_person_context(tmp_path, "nobody") == ""


def test_load_person_context_no_people_dir(tmp_path: Path):
    assert load_person_context(tmp_path, "chris") == ""


def test_load_person_context_profile_only(tmp_path: Path):
    people = tmp_path / "people" / "chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("# Chris\nLikes coffee")

    result = load_person_context(tmp_path, "chris")
    assert "# Chris" in result
    assert "Likes coffee" in result


def test_load_person_context_symlink_resolves(tmp_path: Path):
    people = tmp_path / "people"
    chris = people / "chris"
    chris.mkdir(parents=True)
    (chris / "profile.md").write_text("# Chris")

    (people / "peps").symlink_to("chris")

    result = load_person_context(tmp_path, "peps")
    assert "# Chris" in result


def test_load_person_context_symlink_uses_canonical_name_for_journal(tmp_path: Path):
    people = tmp_path / "people"
    chris = people / "chris"
    chris.mkdir(parents=True)
    (chris / "profile.md").write_text("# Chris")
    (people / "peps").symlink_to("chris")

    journal = tmp_path / "journal"
    journal.mkdir()
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    (journal / f"{today}.md").write_text(
        f"# {today}\n\n- 10:00 | talked to [[people/chris]] about testing\n"
    )

    result = load_person_context(tmp_path, "peps")
    assert "[[people/chris]]" in result
    assert "Recent journal mentions" in result


def test_load_person_context_with_journal_mentions(tmp_path: Path):
    people = tmp_path / "people" / "chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("# Chris")

    journal = tmp_path / "journal"
    journal.mkdir()
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    (journal / f"{today}.md").write_text(
        f"# {today}\n\n"
        "- 10:00 | talked to [[people/chris]] about testing\n"
        "- 11:00 | did some cleanup\n"
    )

    result = load_person_context(tmp_path, "chris")
    assert "[[people/chris]]" in result
    assert "Recent journal mentions" in result
    assert "did some cleanup" not in result


def test_load_person_context_journal_date_cutoff(tmp_path: Path):
    people = tmp_path / "people" / "chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("# Chris")

    journal = tmp_path / "journal"
    journal.mkdir()

    old_date = (datetime.now().astimezone() - timedelta(days=10)).strftime("%Y-%m-%d")
    (journal / f"{old_date}.md").write_text(
        f"# {old_date}\n\n- 10:00 | talked to [[people/chris]] long ago\n"
    )

    result = load_person_context(tmp_path, "chris")
    assert "long ago" not in result


def test_load_person_context_no_profile_file(tmp_path: Path):
    (tmp_path / "people" / "ghost").mkdir(parents=True)
    result = load_person_context(tmp_path, "ghost")
    assert result == ""


def test_load_person_context_case_insensitive_wikilink(tmp_path: Path):
    people = tmp_path / "people" / "Chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("# Chris")

    journal = tmp_path / "journal"
    journal.mkdir()
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    (journal / f"{today}.md").write_text(
        f"# {today}\n\n- 10:00 | talked to [[People/Chris]] about things\n"
    )

    result = load_person_context(tmp_path, "Chris")
    assert "about things" in result
