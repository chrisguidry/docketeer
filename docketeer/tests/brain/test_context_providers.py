"""Tests for the context provider extension point in Brain."""

from pathlib import Path
from typing import Any

from docketeer.brain import Brain
from docketeer.prompt import MessageContent, MessageParam
from docketeer.tools import ToolContext

from ..conftest import FakeMessage, make_text_block


class FakeContextProvider:
    """Test double for the ContextProvider protocol."""

    def for_user(self, workspace: Path, username: str) -> list[MessageParam]:
        profile_dir = workspace / "people" / username
        if profile_dir.is_dir():
            return [
                MessageParam(
                    role="system",
                    content=f"## What I know about @{username}\n\ntest profile",
                )
            ]
        return [
            MessageParam(
                role="system",
                content=f"No profile for @{username}",
            )
        ]

    def for_line(self, workspace: Path, slug: str) -> list[MessageParam]:
        line_file = workspace / "lines" / f"{slug}.md"
        if line_file.is_file():
            return [
                MessageParam(
                    role="system",
                    content=f"## Line notes: {slug}\n\n{line_file.read_text()}",
                )
            ]
        return []


async def test_context_provider_for_user_called(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    (tool_context.workspace / "people" / "chris").mkdir(parents=True)
    brain._context_providers = [FakeContextProvider()]
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    await brain.process("room1", MessageContent(username="chris", text="hello"))

    messages = brain._conversations["room1"]
    profile_msg = next(
        (
            m
            for m in messages
            if m.role == "system" and "What I know about" in m.content
        ),
        None,
    )
    assert profile_msg is not None


async def test_context_provider_for_user_not_reloaded(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    brain._context_providers = [FakeContextProvider()]
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]
    await brain.process("room1", MessageContent(username="chris", text="hi"))
    await brain.process("room1", MessageContent(username="chris", text="hey"))

    system_msgs = [m for m in brain._conversations["room1"] if m.role == "system"]
    assert len(system_msgs) == 1


async def test_context_provider_for_line_called(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    lines = tool_context.workspace / "lines"
    lines.mkdir()
    (lines / "general.md").write_text("Weekly sync")
    brain._context_providers = [FakeContextProvider()]
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    await brain.process(
        "room1", MessageContent(username="chris", text="hello"), room_slug="general"
    )

    messages = brain._conversations["room1"]
    line_msg = next(
        (m for m in messages if m.role == "system" and "Line notes:" in m.content),
        None,
    )
    assert line_msg is not None
    assert "Weekly sync" in line_msg.content


async def test_context_provider_line_loaded_for_task_lines(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    lines = tool_context.workspace / "lines"
    lines.mkdir()
    (lines / "reverie.md").write_text("Reverie context")
    brain._context_providers = [FakeContextProvider()]
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="ok")])]
    await brain.process(
        "reverie",
        MessageContent(text="think"),
    )

    messages = brain._conversations["reverie"]
    line_messages = [
        m for m in messages if m.role == "system" and "Line notes:" in m.content
    ]
    assert len(line_messages) == 1
    assert "Reverie context" in line_messages[0].content


async def test_context_reinjected_after_compaction(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    (tool_context.workspace / "people" / "chris").mkdir(parents=True)
    lines = tool_context.workspace / "lines"
    lines.mkdir()
    (lines / "general.md").write_text("Weekly sync")
    brain._context_providers = [FakeContextProvider()]

    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text=f"Reply {i}")]) for i in range(6)
    ]

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

    brain._token_counts["room1"] = 150_000

    await brain.process(
        "room1",
        MessageContent(username="chris", text="world"),
        room_slug="general",
    )

    messages = brain._conversations["room1"]
    profile_idx = next(
        i
        for i, m in enumerate(messages)
        if m.role == "system" and "What I know about @chris" in m.content
    )
    line_idx = next(
        i
        for i, m in enumerate(messages)
        if m.role == "system" and "Line notes: general" in m.content
    )
    summary_idx = next(
        i
        for i, m in enumerate(messages)
        if m.role == "user" and "[Earlier conversation summary]" in m.content
    )

    assert profile_idx < summary_idx
    assert line_idx < summary_idx


async def test_no_providers_means_no_context(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    brain._context_providers = []
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    await brain.process("room1", MessageContent(username="chris", text="hello"))

    messages = brain._conversations["room1"]
    system_msgs = [m for m in messages if m.role == "system"]
    assert len(system_msgs) == 0


async def test_no_username_skips_profile_loading(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    brain._context_providers = [FakeContextProvider()]
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="ok")])]
    await brain.process("room1", MessageContent(text="a signal"))

    assert brain._profiles_loaded["room1"] == set()
