"""Tests for the skill catalog prompt provider."""

from pathlib import Path

from docketeer_agentskills.prompt import provide_skill_catalog

from .conftest import make_skill


def test_provide_skill_catalog_no_skills_dir(workspace: Path):
    blocks = provide_skill_catalog(workspace)
    assert blocks == []


def test_provide_skill_catalog_empty_skills_dir(skills_dir: Path, workspace: Path):
    blocks = provide_skill_catalog(workspace)
    assert blocks == []


def test_provide_skill_catalog_with_skills(skills_dir: Path, workspace: Path):
    make_skill(skills_dir, name="alpha", description="Alpha skill")
    make_skill(skills_dir, name="beta", description="Beta skill")
    blocks = provide_skill_catalog(workspace)
    assert len(blocks) == 1
    text = blocks[0].text
    assert "## Installed skills" in text
    assert "**alpha**: Alpha skill" in text
    assert "**beta**: Beta skill" in text
    assert "activate_skill" in text
