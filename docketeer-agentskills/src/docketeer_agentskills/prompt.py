"""System prompt provider for installed skills."""

from pathlib import Path

from docketeer.prompt import SystemBlock

from .discovery import discover_skills


def provide_skill_catalog(workspace: Path) -> list[SystemBlock]:
    """Build a skill catalog block for the system prompt."""
    skills = discover_skills(workspace / "skills")
    if not skills:
        return []

    lines = [
        "## Installed skills",
        "",
        "Use `activate_skill` to load a skill's full instructions when relevant.",
        "",
    ]
    for skill in skills.values():
        lines.append(f"- **{skill.name}**: {skill.description}")

    return [SystemBlock(text="\n".join(lines))]
