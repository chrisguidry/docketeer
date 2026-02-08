"""Shared test fixtures for docketeer-agentskills."""

from pathlib import Path

import pytest

from docketeer.tools import ToolContext


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


@pytest.fixture()
def skills_dir(workspace: Path) -> Path:
    d = workspace / "skills"
    d.mkdir()
    return d


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, room_id="room1")


def make_skill(
    skills_dir: Path,
    name: str = "test-skill",
    description: str = "A test skill",
    body: str = "## Instructions\n\nDo the thing.",
    extra_frontmatter: str = "",
) -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = f"name: {name}\ndescription: {description}"
    if extra_frontmatter:
        frontmatter += f"\n{extra_frontmatter}"
    (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}")
    return skill_dir
