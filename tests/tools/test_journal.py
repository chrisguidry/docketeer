"""Tests for journal tools (add, read, search)."""

from datetime import datetime

from docketeer.tools import ToolContext, registry


async def test_journal_add_new_day(ctx: ToolContext):
    result = await registry.execute("journal_add", {"entry": "test entry #test"}, ctx)
    assert "Added to journal" in result
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    path = ctx.workspace / "journal" / f"{today}.md"
    content = path.read_text()
    assert content.startswith(f"# {today}")
    assert "test entry #test" in content


async def test_journal_add_existing_day(ctx: ToolContext):
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    journal = ctx.workspace / "journal"
    journal.mkdir()
    path = journal / f"{today}.md"
    path.write_text(f"# {today}\n\n- 09:00 | first entry\n")

    await registry.execute("journal_add", {"entry": "second entry"}, ctx)
    content = path.read_text()
    assert "first entry" in content
    assert "second entry" in content


async def test_journal_read_today(ctx: ToolContext):
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    journal = ctx.workspace / "journal"
    journal.mkdir()
    (journal / f"{today}.md").write_text(f"# {today}\n\n- 10:00 | today entry\n")

    result = await registry.execute("journal_read", {}, ctx)
    assert "today entry" in result


async def test_journal_read_specific_date(ctx: ToolContext):
    journal = ctx.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-15.md").write_text("# 2026-01-15\n\n- 10:00 | old entry\n")

    result = await registry.execute("journal_read", {"date": "2026-01-15"}, ctx)
    assert "old entry" in result


async def test_journal_read_date_not_found(ctx: ToolContext):
    journal = ctx.workspace / "journal"
    journal.mkdir()
    result = await registry.execute("journal_read", {"date": "2020-01-01"}, ctx)
    assert "No journal for 2020-01-01" in result


async def test_journal_read_range(ctx: ToolContext):
    journal = ctx.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-10.md").write_text("# 2026-01-10\n- entry A\n")
    (journal / "2026-01-15.md").write_text("# 2026-01-15\n- entry B\n")
    (journal / "2026-01-20.md").write_text("# 2026-01-20\n- entry C\n")

    result = await registry.execute(
        "journal_read", {"start": "2026-01-10", "end": "2026-01-15"}, ctx
    )
    assert "entry A" in result
    assert "entry B" in result
    assert "entry C" not in result


async def test_journal_read_range_start_filter(ctx: ToolContext):
    journal = ctx.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-05.md").write_text("# too early\n- before range\n")
    (journal / "2026-01-15.md").write_text("# 2026-01-15\n- in range\n")

    result = await registry.execute("journal_read", {"start": "2026-01-10"}, ctx)
    assert "in range" in result
    assert "too early" not in result


async def test_journal_read_range_empty(ctx: ToolContext):
    journal = ctx.workspace / "journal"
    journal.mkdir()
    result = await registry.execute(
        "journal_read", {"start": "2099-01-01", "end": "2099-12-31"}, ctx
    )
    assert "No journal entries for range" in result


async def test_journal_read_no_journal_dir(ctx: ToolContext):
    result = await registry.execute("journal_read", {}, ctx)
    assert "No journal entries yet" in result


async def test_journal_read_today_no_entry(ctx: ToolContext):
    journal = ctx.workspace / "journal"
    journal.mkdir()
    (journal / "2020-01-01.md").write_text("old stuff")
    result = await registry.execute("journal_read", {}, ctx)
    assert "No journal entries for today" in result


async def test_journal_search(ctx: ToolContext):
    journal = ctx.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-15.md").write_text(
        "# 2026-01-15\n\n- 10:00 | talked to chris\n- 11:00 | lunch\n"
    )
    result = await registry.execute("journal_search", {"query": "chris"}, ctx)
    assert "talked to chris" in result
    assert "lunch" not in result


async def test_journal_search_no_matches(ctx: ToolContext):
    journal = ctx.workspace / "journal"
    journal.mkdir()
    (journal / "2026-01-15.md").write_text("# 2026-01-15\n- 10:00 | stuff\n")
    result = await registry.execute("journal_search", {"query": "xyz"}, ctx)
    assert "No journal entries matching" in result


async def test_journal_search_no_journal_dir(ctx: ToolContext):
    result = await registry.execute("journal_search", {"query": "anything"}, ctx)
    assert "No journal entries yet" in result


async def test_journal_search_max_results(ctx: ToolContext):
    journal = ctx.workspace / "journal"
    journal.mkdir()
    lines = "\n".join(f"- 10:{i:02d} | match entry {i}" for i in range(60))
    (journal / "2026-01-15.md").write_text(f"# 2026-01-15\n{lines}\n")
    result = await registry.execute("journal_search", {"query": "match"}, ctx)
    assert result.count("\n") == 49  # 50 lines, 49 newlines
