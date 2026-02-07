"""Tests for journal tools (add, read, search)."""

from datetime import datetime

from docketeer.tools import ToolContext, registry


async def test_journal_add_new_day(tool_context: ToolContext):
    result = await registry.execute(
        "journal_add", {"entry": "test entry #test"}, tool_context
    )
    assert "Added to journal" in result
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    path = tool_context.workspace / "journal" / f"{today}.md"
    content = path.read_text()
    assert content.startswith(f"# {today}")
    assert "test entry #test" in content


async def test_journal_add_existing_day(tool_context: ToolContext):
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    path = journal / f"{today}.md"
    path.write_text(f"# {today}\n\n- 09:00 | first entry\n")

    await registry.execute("journal_add", {"entry": "second entry"}, tool_context)
    content = path.read_text()
    assert "first entry" in content
    assert "second entry" in content


async def test_journal_read_today(tool_context: ToolContext):
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    (journal / f"{today}.md").write_text(f"# {today}\n\n- 10:00 | today entry\n")

    result = await registry.execute("journal_read", {}, tool_context)
    assert "today entry" in result


async def test_journal_read_specific_date(tool_context: ToolContext):
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-15.md").write_text("# 2026-01-15\n\n- 10:00 | old entry\n")

    result = await registry.execute(
        "journal_read", {"date": "2026-01-15"}, tool_context
    )
    assert "old entry" in result


async def test_journal_read_date_not_found(tool_context: ToolContext):
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    result = await registry.execute(
        "journal_read", {"date": "2020-01-01"}, tool_context
    )
    assert "No journal for 2020-01-01" in result


async def test_journal_read_range(tool_context: ToolContext):
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-10.md").write_text("# 2026-01-10\n- entry A\n")
    (journal / "2026-01-15.md").write_text("# 2026-01-15\n- entry B\n")
    (journal / "2026-01-20.md").write_text("# 2026-01-20\n- entry C\n")

    result = await registry.execute(
        "journal_read", {"start": "2026-01-10", "end": "2026-01-15"}, tool_context
    )
    assert "entry A" in result
    assert "entry B" in result
    assert "entry C" not in result


async def test_journal_read_range_start_filter(tool_context: ToolContext):
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-05.md").write_text("# too early\n- before range\n")
    (journal / "2026-01-15.md").write_text("# 2026-01-15\n- in range\n")

    result = await registry.execute(
        "journal_read", {"start": "2026-01-10"}, tool_context
    )
    assert "in range" in result
    assert "too early" not in result


async def test_journal_read_range_empty(tool_context: ToolContext):
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    result = await registry.execute(
        "journal_read", {"start": "2099-01-01", "end": "2099-12-31"}, tool_context
    )
    assert "No journal entries for range" in result


async def test_journal_read_no_journal_dir(tool_context: ToolContext):
    result = await registry.execute("journal_read", {}, tool_context)
    assert "No journal entries yet" in result


async def test_journal_read_today_no_entry(tool_context: ToolContext):
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    (journal / "2020-01-01.md").write_text("old stuff")
    result = await registry.execute("journal_read", {}, tool_context)
    assert "No journal entries for today" in result


async def test_journal_search(tool_context: ToolContext):
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-15.md").write_text(
        "# 2026-01-15\n\n- 10:00 | talked to chris\n- 11:00 | lunch\n"
    )
    result = await registry.execute("journal_search", {"query": "chris"}, tool_context)
    assert "talked to chris" in result
    assert "lunch" not in result


async def test_journal_search_no_matches(tool_context: ToolContext):
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-15.md").write_text("# 2026-01-15\n- 10:00 | stuff\n")
    result = await registry.execute("journal_search", {"query": "xyz"}, tool_context)
    assert "No journal entries matching" in result


async def test_journal_search_no_journal_dir(tool_context: ToolContext):
    result = await registry.execute(
        "journal_search", {"query": "anything"}, tool_context
    )
    assert "No journal entries yet" in result


async def test_journal_search_max_results(tool_context: ToolContext):
    journal = tool_context.workspace / "journal"
    journal.mkdir()
    lines = "\n".join(f"- 10:{i:02d} | match entry {i}" for i in range(60))
    (journal / "2026-01-15.md").write_text(f"# 2026-01-15\n{lines}\n")
    result = await registry.execute("journal_search", {"query": "match"}, tool_context)
    assert result.count("\n") == 49  # 50 lines, 49 newlines
