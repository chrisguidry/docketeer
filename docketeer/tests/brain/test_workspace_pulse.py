"""Tests for workspace pulse injection in Brain.process()."""

from typing import Any

import pytest

from docketeer.brain import Brain
from docketeer.prompt import MessageContent
from docketeer.testing import MemoryWatcher

from ..conftest import FakeMessage, make_text_block


def _pulse_msgs(brain: Brain, room_id: str = "room1") -> list:
    return [
        m
        for m in brain._conversations[room_id]
        if "workspace updated" in str(m.content)
    ]


@pytest.fixture()
def watcher(brain: Brain) -> MemoryWatcher:
    assert isinstance(brain._watcher, MemoryWatcher)
    return brain._watcher


async def test_first_process_no_pulse(brain: Brain, fake_messages: Any):
    """First drain catches up — no pulse injected."""
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content)

    assert len(_pulse_msgs(brain)) == 0


async def test_external_change_injects_pulse(
    brain: Brain, fake_messages: Any, watcher: MemoryWatcher
):
    """Changes notified between process calls produce a pulse."""
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]

    content1 = MessageContent(username="chris", text="hello")
    await brain.process("room1", content1)

    watcher.notify("notes/todo.md")

    content2 = MessageContent(username="chris", text="what changed?")
    await brain.process("room1", content2)

    pulses = _pulse_msgs(brain)
    assert len(pulses) == 1
    assert pulses[0].role == "user"
    assert "notes/todo.md" in pulses[0].content


async def test_pulse_appears_before_user_content(
    brain: Brain, fake_messages: Any, watcher: MemoryWatcher
):
    """The pulse message appears before the user's message in conversation order."""
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]

    content1 = MessageContent(username="chris", text="hello")
    await brain.process("room1", content1)

    watcher.notify("notes/changed.md")

    content2 = MessageContent(username="chris", text="continue")
    await brain.process("room1", content2)

    messages = brain._conversations["room1"]
    pulse_idx = next(
        i for i, m in enumerate(messages) if "workspace updated" in str(m.content)
    )
    user_idx = next(
        i
        for i, m in enumerate(messages)
        if m.role == "user" and "continue" in str(m.content)
    )
    assert pulse_idx < user_idx


async def test_no_pulse_when_no_changes(brain: Brain, fake_messages: Any):
    """Two process calls with no notify — no pulse injected."""
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]

    content1 = MessageContent(username="chris", text="hello")
    await brain.process("room1", content1)

    content2 = MessageContent(username="chris", text="again")
    await brain.process("room1", content2)

    assert len(_pulse_msgs(brain)) == 0


async def test_pulse_format_few_files(
    brain: Brain, fake_messages: Any, watcher: MemoryWatcher
):
    """With 3 files changed, the pulse lists each path."""
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]

    content1 = MessageContent(username="chris", text="hello")
    await brain.process("room1", content1)

    watcher.notify("a.md", "b.md", "c.md")

    content2 = MessageContent(username="chris", text="what?")
    await brain.process("room1", content2)

    pulses = _pulse_msgs(brain)
    assert len(pulses) == 1
    assert "a.md" in pulses[0].content
    assert "b.md" in pulses[0].content
    assert "c.md" in pulses[0].content


async def test_pulse_format_many_files(
    brain: Brain, fake_messages: Any, watcher: MemoryWatcher
):
    """With >5 files changed, the pulse shows a count instead."""
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]

    content1 = MessageContent(username="chris", text="hello")
    await brain.process("room1", content1)

    watcher.notify(*[f"file{i}.md" for i in range(8)])

    content2 = MessageContent(username="chris", text="what?")
    await brain.process("room1", content2)

    pulses = _pulse_msgs(brain)
    assert len(pulses) == 1
    assert "8 files changed" in pulses[0].content


async def test_own_changes_absorbed(
    brain: Brain, fake_messages: Any, watcher: MemoryWatcher
):
    """End-of-turn drain absorbs own tool writes so they don't echo back."""
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]

    content1 = MessageContent(username="chris", text="hello")
    await brain.process("room1", content1)

    # No notify between turns — nothing should pulse
    content2 = MessageContent(username="chris", text="again")
    await brain.process("room1", content2)

    assert len(_pulse_msgs(brain)) == 0
