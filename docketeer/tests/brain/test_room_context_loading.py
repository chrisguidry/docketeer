"""Tests for room context loading in the brain."""

from typing import Any

from docketeer.brain import Brain
from docketeer.prompt import MessageContent
from docketeer.tools import ToolContext

from ..conftest import FakeMessage, make_text_block


async def test_room_context_loaded_on_first_message(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    rooms = tool_context.workspace / "rooms"
    rooms.mkdir()
    (rooms / "general.md").write_text("Weekly sync every Monday")

    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content, room_slug="general")

    messages = brain._conversations["room1"]
    room_msg = next(
        (
            m
            for m in messages
            if m.role == "system" and "Room notes: general" in m.content
        ),
        None,
    )
    assert room_msg is not None
    assert "Weekly sync every Monday" in room_msg.content


async def test_room_context_not_reloaded_on_second_message(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    rooms = tool_context.workspace / "rooms"
    rooms.mkdir()
    (rooms / "general.md").write_text("Room notes here")

    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]

    await brain.process(
        "room1", MessageContent(username="chris", text="hi"), room_slug="general"
    )
    await brain.process(
        "room1", MessageContent(username="chris", text="hey"), room_slug="general"
    )

    messages = brain._conversations["room1"]
    room_messages = [
        m for m in messages if m.role == "system" and "Room notes:" in m.content
    ]
    assert len(room_messages) == 1


async def test_room_context_reset_after_compaction(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    rooms = tool_context.workspace / "rooms"
    rooms.mkdir()
    (rooms / "general.md").write_text("Room notes here")

    brain._room_token_counts["room1"] = 150_000

    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Summary")]),
        FakeMessage(content=[make_text_block(text="After compaction")]),
    ]

    await brain.process(
        "room1", MessageContent(username="chris", text="hi"), room_slug="general"
    )
    await brain.process(
        "room1", MessageContent(username="chris", text="hey"), room_slug="general"
    )

    messages = brain._conversations["room1"]
    room_messages = [
        m for m in messages if m.role == "system" and "Room notes:" in m.content
    ]
    assert len(room_messages) == 1


async def test_room_context_skipped_for_dunder_rooms(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    rooms = tool_context.workspace / "rooms"
    rooms.mkdir()
    (rooms / "reverie.md").write_text("Should not load")

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


async def test_no_system_message_when_room_file_missing(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    await brain.process(
        "room1", MessageContent(username="chris", text="hi"), room_slug="general"
    )

    messages = brain._conversations["room1"]
    room_messages = [
        m for m in messages if m.role == "system" and "Room notes:" in m.content
    ]
    assert len(room_messages) == 0


async def test_room_context_falls_back_to_room_id(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    rooms = tool_context.workspace / "rooms"
    rooms.mkdir()
    (rooms / "room1.md").write_text("Fallback room notes")

    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    await brain.process("room1", MessageContent(username="chris", text="hi"))

    messages = brain._conversations["room1"]
    room_msg = next(
        (
            m
            for m in messages
            if m.role == "system" and "Room notes: room1" in m.content
        ),
        None,
    )
    assert room_msg is not None
    assert "Fallback room notes" in room_msg.content
