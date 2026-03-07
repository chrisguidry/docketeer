"""Shared test helpers for docketeer-agentskills."""

from pathlib import Path


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
