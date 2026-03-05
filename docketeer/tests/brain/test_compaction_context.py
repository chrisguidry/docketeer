"""Tests that context (profiles, room notes) is prepended after compaction."""

from typing import Any

from docketeer.brain import Brain
from docketeer.prompt import MessageContent
from docketeer.tools import ToolContext

from ..conftest import FakeMessage, make_text_block


async def test_context_prepended_before_summary_after_compaction(
    brain: Brain,
    fake_messages: Any,
    tool_context: ToolContext,
):
    """After compaction, profile and room context appear before the summary."""
    profile_dir = tool_context.workspace / "people" / "chris"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("Birthday: June 4")

    rooms = tool_context.workspace / "rooms"
    rooms.mkdir()
    (rooms / "general.md").write_text("Weekly sync every Monday")

    # 4 replies for the conversation + 1 for summarize_transcript + 1 after compaction
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text=f"Reply {i}")]) for i in range(6)
    ]

    # Build enough history (>6 messages) so compaction actually summarizes
    await brain.process(
        "room1",
        MessageContent(username="chris", text="hello"),
        room_slug="general",
    )
    for i in range(3):
        await brain.process(
            "room1",
            MessageContent(username="chris", text=f"msg {i}"),
            room_slug="general",
        )

    # Force compaction on next message
    brain._room_token_counts["room1"] = 150_000

    await brain.process(
        "room1",
        MessageContent(username="chris", text="world"),
        room_slug="general",
    )

    messages = brain._conversations["room1"]

    # Find positions of context and summary messages
    profile_idx = next(
        i
        for i, m in enumerate(messages)
        if m.role == "system" and "What I know about @chris" in m.content
    )
    room_idx = next(
        i
        for i, m in enumerate(messages)
        if m.role == "system" and "Room notes: general" in m.content
    )
    summary_idx = next(
        i
        for i, m in enumerate(messages)
        if m.role == "user" and "[Earlier conversation summary]" in m.content
    )

    assert profile_idx < summary_idx
    assert room_idx < summary_idx


async def test_no_profile_nudge_reinjected_after_compaction(
    brain: Brain,
    fake_messages: Any,
    tool_context: ToolContext,
):
    """The 'no profile yet' nudge is NOT re-injected after compaction."""
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text=f"Reply {i}")]) for i in range(6)
    ]

    # Build enough history so compaction actually summarizes
    for i in range(4):
        await brain.process(
            "room1", MessageContent(username="unknown", text=f"msg {i}")
        )

    brain._room_token_counts["room1"] = 150_000

    await brain.process("room1", MessageContent(username="unknown", text="hey"))

    messages = brain._conversations["room1"]
    nudges = [
        m
        for m in messages
        if m.role == "system" and "don't have a profile" in m.content
    ]
    # The nudge should not reappear — only from the first message, which was
    # compacted away. The re-inject skips users without actual profile content.
    assert len(nudges) == 0


async def test_new_user_after_compaction_still_gets_profile(
    brain: Brain,
    fake_messages: Any,
    tool_context: ToolContext,
):
    """A new user speaking after compaction still gets their profile loaded."""
    chris_dir = tool_context.workspace / "people" / "chris"
    chris_dir.mkdir(parents=True)
    (chris_dir / "profile.md").write_text("Birthday: June 4")

    sarah_dir = tool_context.workspace / "people" / "sarah"
    sarah_dir.mkdir(parents=True)
    (sarah_dir / "profile.md").write_text("Birthday: December 25")

    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text=f"Reply {i}")]) for i in range(7)
    ]

    # Build enough history so compaction actually summarizes
    for i in range(4):
        await brain.process("room1", MessageContent(username="chris", text=f"msg {i}"))

    brain._room_token_counts["room1"] = 150_000

    # Chris speaks again (triggers compaction + re-inject)
    await brain.process("room1", MessageContent(username="chris", text="hey"))

    # Sarah speaks for the first time — should still get her profile
    await brain.process("room1", MessageContent(username="sarah", text="hello"))

    messages = brain._conversations["room1"]
    sarah_profile = next(
        (
            m
            for m in messages
            if m.role == "system" and "What I know about @sarah" in m.content
        ),
        None,
    )
    assert sarah_profile is not None
    assert "December 25" in sarah_profile.content
