"""Skill management tools."""

import shutil
import subprocess

from docketeer.tools import ToolContext, _safe_path, registry

from .discovery import discover_skills, parse_skill


@registry.tool
async def list_skills(ctx: ToolContext) -> str:
    """List all installed skills with their descriptions."""
    skills = discover_skills(ctx.workspace / "skills")
    if not skills:
        return "No skills installed."
    lines = []
    for skill in skills.values():
        lines.append(f"- {skill.name}: {skill.description}")
    return "\n".join(lines)


@registry.tool
async def activate_skill(ctx: ToolContext, name: str) -> str:
    """Load the full instructions for an installed skill.

    name: skill name to activate
    """
    skill_dir = _safe_path(ctx.workspace, f"skills/{name}")
    if not skill_dir.is_dir():
        return f"Skill not found: {name}"
    try:
        skill = parse_skill(skill_dir)
    except (ValueError, FileNotFoundError) as e:
        return f"Error loading skill {name}: {e}"
    return skill.body


@registry.tool
async def read_skill_file(ctx: ToolContext, name: str, path: str) -> str:
    """Read a file from an installed skill's directory.

    name: skill name
    path: relative path within the skill directory
    """
    skill_dir = _safe_path(ctx.workspace, f"skills/{name}")
    if not skill_dir.is_dir():
        return f"Skill not found: {name}"
    target = (skill_dir / path).resolve()
    if not str(target).startswith(str(skill_dir.resolve())):
        return f"Path '{path}' is outside the skill directory"
    if not target.exists():
        return f"File not found: {path}"
    if target.is_dir():
        return "\n".join(
            f"{e.name}/" if e.is_dir() else e.name for e in sorted(target.iterdir())
        )
    try:
        return target.read_text()
    except UnicodeDecodeError:
        return f"Cannot read binary file: {path}"


@registry.tool
async def install_skill(ctx: ToolContext, url: str, name: str = "") -> str:
    """Install a skill from a git repository.

    url: git repository URL to clone
    name: skill name (derived from URL if empty)
    """
    if not shutil.which("git"):
        return "git is not installed — cannot clone skill repositories"

    if not name:
        name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")

    skills_dir = ctx.workspace / "skills"
    skills_dir.mkdir(exist_ok=True)
    target = skills_dir / name

    if target.exists():
        return f"Skill {name!r} is already installed"

    result = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if target.exists():
            shutil.rmtree(target)
        return f"Failed to clone: {result.stderr.strip()}"

    if not (target / "SKILL.md").exists():
        shutil.rmtree(target)
        return "Repository does not contain a SKILL.md file"

    try:
        skill = parse_skill(target)
    except (ValueError, FileNotFoundError) as e:
        shutil.rmtree(target)
        return f"Invalid skill: {e}"

    return f"Installed skill {skill.name!r}: {skill.description}"


@registry.tool
async def uninstall_skill(ctx: ToolContext, name: str) -> str:
    """Remove an installed skill.

    name: skill name to remove
    """
    skill_dir = _safe_path(ctx.workspace, f"skills/{name}")
    if not skill_dir.is_dir():
        return f"Skill not found: {name}"
    shutil.rmtree(skill_dir)
    return f"Removed skill {name!r}"
