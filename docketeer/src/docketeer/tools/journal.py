"""Journal tools for timestamped daily entries."""

from datetime import datetime
from pathlib import Path

from . import ToolContext, registry


def _journal_dir(workspace: Path) -> Path:
    return workspace / "journal"


def _journal_path_for_date(workspace: Path, date: str) -> Path:
    return _journal_dir(workspace) / f"{date}.md"


@registry.tool(emoji=":pencil:")
async def journal_add(ctx: ToolContext, entry: str) -> str:
    """Add a timestamped entry to today's journal. Use [[wikilinks]] to reference workspace files.

    entry: text to append (e.g. "talked to [[people/chris]] about the project")
    """
    now = datetime.now().astimezone()
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H:%M")
    path = _journal_path_for_date(ctx.workspace, date)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text(f"# {date}\n\n- {time} | {entry}\n")
    else:
        with path.open("a") as f:
            f.write(f"- {time} | {entry}\n")

    return f"Added to journal at {date} {time}"


@registry.tool(emoji=":pencil:")
async def journal_read(
    ctx: ToolContext, date: str = "", start: str = "", end: str = ""
) -> str:
    """Read journal entries. Defaults to today. Use date for a single day, or start/end for a range.

    date: read a specific day (ISO format, e.g. 2026-02-05)
    start: start of date range (ISO format)
    end: end of date range (ISO format)
    """
    journal_dir = _journal_dir(ctx.workspace)
    if not journal_dir.exists():
        return "No journal entries yet"

    if date:
        path = _journal_path_for_date(ctx.workspace, date)
        if not path.exists():
            return f"No journal for {date}"
        return path.read_text()

    if start or end:
        files = sorted(journal_dir.glob("*.md"))
        entries = []
        for path in files:
            file_date = path.stem
            if start and file_date < start:
                continue
            if end and file_date > end:
                continue
            entries.append(path.read_text())
        if not entries:
            return f"No journal entries for range {start}–{end}"
        return "\n\n".join(entries)

    # Default: today
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    path = _journal_path_for_date(ctx.workspace, today)
    if not path.exists():
        return f"No journal entries for today ({today})"
    return path.read_text()


@registry.tool(emoji=":pencil:")
async def journal_search(ctx: ToolContext, query: str) -> str:
    """Search across all journal entries.

    query: text to search for (case-insensitive)
    """
    journal_dir = _journal_dir(ctx.workspace)
    if not journal_dir.exists():
        return "No journal entries yet"

    query_lower = query.lower()
    matches = []

    for path in sorted(journal_dir.glob("*.md")):
        file_date = path.stem
        for line in path.read_text().splitlines():
            if not line.startswith("- "):
                continue
            if query_lower in line.lower():
                matches.append(f"[{file_date}] {line}")
                if len(matches) >= 50:
                    return "\n".join(matches)

    if not matches:
        return f"No journal entries matching '{query}'"
    return "\n".join(matches)
