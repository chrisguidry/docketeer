"""Room context loading."""

from datetime import datetime, timedelta
from pathlib import Path


def load_room_context(workspace: Path, room_slug: str) -> str:
    """Build a context string with room notes and recent journal mentions.

    Looks for rooms/{room_slug}.md in the workspace. If it exists, returns its
    content along with any recent journal entries that mention the room via
    [[rooms/{room_slug}]] wikilinks.
    """
    room_file = workspace / "rooms" / f"{room_slug}.md"
    if not room_file.is_file():
        return ""

    parts: list[str] = []
    parts.append(room_file.read_text().rstrip())

    wikilink_pattern = f"[[rooms/{room_slug}]]".lower()

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
