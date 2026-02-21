"""Tests for profile loading in the brain."""

from typing import Any

from docketeer.brain import Brain
from docketeer.prompt import MessageContent
from docketeer.tools import ToolContext

from ..conftest import FakeMessage, make_text_block


async def test_process_loads_profile_on_first_message(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    """Profile is loaded and sent to the model on the first message from a user."""
    profile_dir = tool_context.workspace / "people" / "chris"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("# Chris\n- Birthday: June 4")

    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content)

    messages = brain._conversations["room1"]
    profile_msg = next(
        (
            m
            for m in messages
            if m.role == "system" and "What I know about @chris" in m.content
        ),
        None,
    )
    assert profile_msg is not None
    assert "Birthday: June 4" in profile_msg.content


async def test_process_does_not_reload_profile_on_second_message(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    """Profile is NOT reloaded on subsequent messages from the same user."""
    profile_dir = tool_context.workspace / "people" / "chris"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("# Chris\n- Birthday: June 4")

    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]

    content1 = MessageContent(username="chris", text="hello")
    await brain.process("room1", content1)

    content2 = MessageContent(username="chris", text="another")
    await brain.process("room1", content2)

    messages = brain._conversations["room1"]
    profile_messages = [m for m in messages if m.role == "system"]
    assert len(profile_messages) == 1
    assert "What I know about @chris" in profile_messages[0].content


async def test_process_resets_profiles_after_compaction(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    """Profiles are reset after compaction clears the conversation."""
    profile_dir = tool_context.workspace / "people" / "chris"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.md").write_text("# Chris\n- Birthday: June 4")

    brain._room_token_counts["room1"] = 150_000

    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Summary")]),
        FakeMessage(content=[make_text_block(text="After compaction")]),
    ]

    content1 = MessageContent(username="chris", text="hello")
    await brain.process("room1", content1)

    messages_after_first = brain._conversations["room1"]
    profile_before = [
        m
        for m in messages_after_first
        if m.role == "system" and "What I know about @chris" in m.content
    ]
    assert len(profile_before) == 1

    content2 = MessageContent(username="chris", text="another")
    await brain.process("room1", content2)

    messages_after_second = brain._conversations["room1"]
    profile_after = [
        m
        for m in messages_after_second
        if m.role == "system" and "What I know about @chris" in m.content
    ]
    assert len(profile_after) == 1


async def test_process_loads_different_profiles_for_different_users(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    """Each user gets their profile loaded when they first speak."""
    chris_dir = tool_context.workspace / "people" / "chris"
    chris_dir.mkdir(parents=True)
    (chris_dir / "profile.md").write_text("# Chris\n- Birthday: June 4")

    sarah_dir = tool_context.workspace / "people" / "sarah"
    sarah_dir.mkdir(parents=True)
    (sarah_dir / "profile.md").write_text("# Sarah\n- Birthday: December 25")

    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Chris here!")]),
        FakeMessage(content=[make_text_block(text="Sarah here!")]),
        FakeMessage(content=[make_text_block(text="Done!")]),
    ]

    content1 = MessageContent(username="chris", text="hi")
    await brain.process("room1", content1)

    content2 = MessageContent(username="sarah", text="hello")
    await brain.process("room1", content2)

    messages = brain._conversations["room1"]
    chris_profile = next(
        (
            m
            for m in messages
            if m.role == "system" and "What I know about @chris" in m.content
        ),
        None,
    )
    sarah_profile = next(
        (
            m
            for m in messages
            if m.role == "system" and "What I know about @sarah" in m.content
        ),
        None,
    )

    assert chris_profile is not None
    assert sarah_profile is not None
    assert "June 4" in chris_profile.content
    assert "December 25" in sarah_profile.content


async def test_process_no_profile_when_not_exists(
    brain: Brain, fake_messages: Any, tool_context: ToolContext
):
    """When no profile exists, the conversation proceeds normally."""
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="unknown_user", text="hello")
    response = await brain.process("room1", content)

    messages = brain._conversations["room1"]
    profile_messages = [m for m in messages if m.role == "system"]
    assert len(profile_messages) == 0
    assert response.text == "Hi!"
