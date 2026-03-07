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

    def for_room(self, workspace: Path, room_slug: str) -> list[MessageParam]:
        room_file = workspace / "rooms" / f"{room_slug}.md"
        if room_file.is_file():
            return [
                MessageParam(
                    role="system",
                    content=f"## Room notes: {room_slug}\n\n{room_file.read_text()}",
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


async def test_context_provider_for_room_called(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    rooms = tool_context.workspace / "rooms"
    rooms.mkdir()
    (rooms / "general.md").write_text("Weekly sync")
    brain._context_providers = [FakeContextProvider()]
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    await brain.process(
        "room1", MessageContent(username="chris", text="hello"), room_slug="general"
    )

    messages = brain._conversations["room1"]
    room_msg = next(
        (m for m in messages if m.role == "system" and "Room notes:" in m.content),
        None,
    )
    assert room_msg is not None
    assert "Weekly sync" in room_msg.content


async def test_context_provider_room_skipped_for_dunder_rooms(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    rooms = tool_context.workspace / "rooms"
    rooms.mkdir()
    (rooms / "reverie.md").write_text("Should not load")
    brain._context_providers = [FakeContextProvider()]
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="ok")])]
    await brain.process(
        "__task__:reverie",
        MessageContent(username="system", text="think"),
        room_slug="reverie",
    )

    messages = brain._conversations["__task__:reverie"]
    room_messages = [
        m for m in messages if m.role == "system" and "Room notes:" in m.content
    ]
    assert len(room_messages) == 0


async def test_context_reinjected_after_compaction(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    (tool_context.workspace / "people" / "chris").mkdir(parents=True)
    rooms = tool_context.workspace / "rooms"
    rooms.mkdir()
    (rooms / "general.md").write_text("Weekly sync")
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

    brain._room_token_counts["room1"] = 150_000

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


async def test_no_providers_means_no_context(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    brain._context_providers = []
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    await brain.process("room1", MessageContent(username="chris", text="hello"))

    messages = brain._conversations["room1"]
    system_msgs = [m for m in messages if m.role == "system"]
    assert len(system_msgs) == 0
