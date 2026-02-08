"""Tests for skill discovery."""

from pathlib import Path

import pytest

from docketeer_agentskills.discovery import (
    _split_frontmatter,
    discover_skills,
    parse_skill,
)

from .conftest import make_skill


def test_parse_skill(skills_dir: Path):
    skill_dir = make_skill(skills_dir)
    skill = parse_skill(skill_dir)
    assert skill.name == "test-skill"
    assert skill.description == "A test skill"
    assert skill.path == skill_dir
    assert "Instructions" in skill.body


def test_parse_skill_with_license(skills_dir: Path):
    skill_dir = make_skill(skills_dir, extra_frontmatter="license: MIT")
    skill = parse_skill(skill_dir)
    assert skill.license == "MIT"


def test_parse_skill_extra_metadata(skills_dir: Path):
    skill_dir = make_skill(skills_dir, extra_frontmatter="version: '1.0'\nauthor: me")
    skill = parse_skill(skill_dir)
    assert skill.metadata == {"version": "1.0", "author": "me"}


def test_parse_skill_no_skill_md(skills_dir: Path):
    skill_dir = skills_dir / "empty-skill"
    skill_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="No SKILL.md"):
        parse_skill(skill_dir)


def test_parse_skill_invalid_name(skills_dir: Path):
    skill_dir = skills_dir / "Bad_Name"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Bad_Name\ndescription: bad\n---\nbody"
    )
    with pytest.raises(ValueError, match="Invalid skill name"):
        parse_skill(skill_dir)


def test_parse_skill_name_mismatch(skills_dir: Path):
    skill_dir = skills_dir / "wrong-dir"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: correct-name\ndescription: test\n---\nbody"
    )
    with pytest.raises(ValueError, match="does not match directory name"):
        parse_skill(skill_dir)


def test_parse_skill_missing_description(skills_dir: Path):
    skill_dir = skills_dir / "no-desc"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: no-desc\n---\nbody")
    with pytest.raises(ValueError, match="missing a description"):
        parse_skill(skill_dir)


def test_parse_skill_missing_name(skills_dir: Path):
    skill_dir = skills_dir / "no-name"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\ndescription: test\n---\nbody")
    with pytest.raises(ValueError, match="Invalid skill name"):
        parse_skill(skill_dir)


def test_parse_skill_single_char_name(skills_dir: Path):
    skill_dir = skills_dir / "a"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: a\ndescription: one\n---\nbody")
    skill = parse_skill(skill_dir)
    assert skill.name == "a"


def test_discover_skills(skills_dir: Path):
    make_skill(skills_dir, name="skill-a", description="Alpha skill")
    make_skill(skills_dir, name="skill-b", description="Beta skill")
    skills = discover_skills(skills_dir)
    assert set(skills.keys()) == {"skill-a", "skill-b"}


def test_discover_skills_skips_invalid(skills_dir: Path):
    make_skill(skills_dir, name="good-skill", description="Good")
    bad_dir = skills_dir / "Bad_Skill"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text("---\nname: Bad_Skill\ndescription: bad\n---\n")
    skills = discover_skills(skills_dir)
    assert list(skills.keys()) == ["good-skill"]


def test_discover_skills_skips_dirs_without_skill_md(skills_dir: Path):
    make_skill(skills_dir, name="real-skill", description="Real")
    (skills_dir / "not-a-skill").mkdir()
    skills = discover_skills(skills_dir)
    assert list(skills.keys()) == ["real-skill"]


def test_discover_skills_skips_files(skills_dir: Path):
    make_skill(skills_dir, name="real-skill", description="Real")
    (skills_dir / "random-file.txt").write_text("hi")
    skills = discover_skills(skills_dir)
    assert list(skills.keys()) == ["real-skill"]


def test_discover_skills_nonexistent_dir(tmp_path: Path):
    skills = discover_skills(tmp_path / "nope")
    assert skills == {}


def test_split_frontmatter_no_markers():
    fm, body = _split_frontmatter("just markdown")
    assert fm == {}
    assert body == "just markdown"


def test_split_frontmatter_incomplete_markers():
    fm, body = _split_frontmatter("---\nname: test")
    assert fm == {}
    assert body == "---\nname: test"


def test_split_frontmatter_non_dict_yaml():
    fm, body = _split_frontmatter("---\n- list item\n---\nbody")
    assert fm == {}
    assert body == "\nbody"
