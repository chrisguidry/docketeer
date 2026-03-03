"""Tests for workspace pulse injection in Brain.process()."""

from typing import Any

import pytest

from docketeer.brain import Brain
from docketeer.prompt import MessageContent
from docketeer.testing import MemoryWatcher

from ..conftest import FakeMessage, make_text_block


@pytest.fixture()
def watcher(brain: Brain) -> MemoryWatcher:
    assert isinstance(brain._watcher, MemoryWatcher)
    return brain._watcher


async def test_first_process_no_pulse(brain: Brain, fake_messages: Any):
    """First drain catches up — no pulse injected."""
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content)

    system_msgs = [m for m in brain._conversations["room1"] if m.role == "system"]
    pulse_msgs = [m for m in system_msgs if "workspace updated" in m.content]
    assert len(pulse_msgs) == 0


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

    system_msgs = [m for m in brain._conversations["room1"] if m.role == "system"]
    pulse_msgs = [m for m in system_msgs if "workspace updated" in m.content]
    assert len(pulse_msgs) == 1
    assert "notes/todo.md" in pulse_msgs[0].content


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
        i
        for i, m in enumerate(messages)
        if m.role == "system" and "workspace updated" in m.content
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

    system_msgs = [m for m in brain._conversations["room1"] if m.role == "system"]
    pulse_msgs = [m for m in system_msgs if "workspace updated" in m.content]
    assert len(pulse_msgs) == 0


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

    system_msgs = [m for m in brain._conversations["room1"] if m.role == "system"]
    pulse = next(m for m in system_msgs if "workspace updated" in m.content)
    assert "a.md" in pulse.content
    assert "b.md" in pulse.content
    assert "c.md" in pulse.content


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

    system_msgs = [m for m in brain._conversations["room1"] if m.role == "system"]
    pulse = next(m for m in system_msgs if "workspace updated" in m.content)
    assert "8 files changed" in pulse.content


async def test_own_changes_absorbed(brain: Brain, fake_messages: Any):
    """Second drain at end of process prevents self-pulse next turn."""
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="First!")]),
        FakeMessage(content=[make_text_block(text="Second!")]),
    ]

    content1 = MessageContent(username="chris", text="hello")
    await brain.process("room1", content1)

    content2 = MessageContent(username="chris", text="again")
    await brain.process("room1", content2)

    system_msgs = [m for m in brain._conversations["room1"] if m.role == "system"]
    pulse_msgs = [m for m in system_msgs if "workspace updated" in m.content]
    assert len(pulse_msgs) == 0
