"""Line context loading."""

from datetime import datetime, timedelta
from pathlib import Path


def load_line_context(workspace: Path, slug: str) -> str:
    """Build a context string with line notes and recent journal mentions.

    Looks for lines/{slug}.md in the workspace. If it exists, returns its
    content along with any recent journal entries that mention the line via
    [[lines/{slug}]] wikilinks.
    """
    line_file = workspace / "lines" / f"{slug}.md"
    if not line_file.is_file():
        return ""

    parts: list[str] = []
    parts.append(line_file.read_text().rstrip())

    wikilink_pattern = f"[[lines/{slug}]]".lower()

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
