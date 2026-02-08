"""Skill discovery: parse SKILL.md files and scan the skills directory."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    body: str
    license: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


def parse_skill(skill_dir: Path) -> Skill:
    """Parse a SKILL.md file from a skill directory."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"No SKILL.md in {skill_dir}")

    content = skill_md.read_text()
    frontmatter, body = _split_frontmatter(content)

    name = frontmatter.get("name", "")
    if not name or not NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid skill name {name!r}: must be 1-64 lowercase"
            " alphanumeric characters or hyphens"
        )

    if name != skill_dir.name:
        raise ValueError(
            f"Skill name {name!r} does not match directory name {skill_dir.name!r}"
        )

    description = frontmatter.get("description", "")
    if not description:
        raise ValueError(f"Skill {name!r} is missing a description")

    return Skill(
        name=name,
        description=description,
        path=skill_dir,
        body=body.strip(),
        license=frontmatter.get("license", ""),
        metadata={
            k: str(v)
            for k, v in frontmatter.items()
            if k not in {"name", "description", "license"}
        },
    )


def discover_skills(skills_dir: Path) -> dict[str, Skill]:
    """Scan a directory for skill subdirectories and return valid skills."""
    if not skills_dir.is_dir():
        return {}

    skills: dict[str, Skill] = {}
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "SKILL.md").exists():
            continue
        try:
            skill = parse_skill(child)
            skills[skill.name] = skill
        except (ValueError, FileNotFoundError):
            log.warning("Skipping invalid skill in %s", child.name, exc_info=True)

    return skills


def _split_frontmatter(content: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    raw = yaml.safe_load(parts[1])
    frontmatter = raw if isinstance(raw, dict) else {}
    return frontmatter, parts[2]
