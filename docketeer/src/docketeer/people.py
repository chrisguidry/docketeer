"""Person profile loading."""

from datetime import datetime, timedelta
from pathlib import Path


def load_person_context(workspace: Path, username: str) -> str:
    """Build a context string with the person's profile and recent journal mentions.

    Looks up people/{username}/ directly — symlinks resolve naturally via is_dir().
    Uses the resolved (canonical) directory name for journal wikilink scanning.
    """
    person_dir = workspace / "people" / username
    if not person_dir.is_dir():
        return ""

    canonical_name = person_dir.resolve().name

    parts: list[str] = []

    profile = person_dir / "profile.md"
    if profile.exists():
        parts.append(profile.read_text().rstrip())

    wikilink_pattern = f"[[people/{canonical_name}]]".lower()

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
