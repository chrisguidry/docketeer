"""Person profile loading and matching."""

import re
from datetime import datetime, timedelta
from pathlib import Path

_USERNAME_RE = re.compile(r"\*\*Username:\*\*\s*@(\S+)")


def build_person_map(workspace: Path) -> dict[str, str]:
    """Scan people/*/profile.md for **Username:** lines, return {rc_username: person_dir}."""
    people_dir = workspace / "people"
    if not people_dir.is_dir():
        return {}
    mapping: dict[str, str] = {}
    for profile in people_dir.glob("*/profile.md"):
        for line in profile.read_text().splitlines():
            if m := _USERNAME_RE.search(line):
                mapping[m.group(1)] = f"people/{profile.parent.name}"
                break
    return mapping


def load_person_context(
    workspace: Path,
    username: str,
    person_map: dict[str, str],
) -> str:
    """Build a context string with the person's profile and recent journal mentions."""
    person_dir = person_map.get(username)
    if not person_dir:
        return ""

    parts: list[str] = []

    profile = workspace / person_dir / "profile.md"
    if profile.exists():
        parts.append(profile.read_text().rstrip())

    name = Path(person_dir).name
    wikilink_pattern = f"[[people/{name}]]".lower()

    journal_dir = workspace / "journal"
    if journal_dir.is_dir():
        cutoff = (datetime.now().astimezone() - timedelta(days=7)).strftime("%Y-%m-%d")
        mentions: list[str] = []
        for jpath in sorted(journal_dir.glob("*.md")):
            if jpath.stem < cutoff:
                continue
            for line in jpath.read_text().splitlines():
                if line.startswith("- ") and wikilink_pattern in line.lower():
                    mentions.append(f"[{jpath.stem}] {line}")
        if mentions:
            parts.append("Recent journal mentions:\n" + "\n".join(mentions))

    return "\n\n".join(parts)
