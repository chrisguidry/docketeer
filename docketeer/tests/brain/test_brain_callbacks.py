"""Tests for on_text and interrupted callbacks in the Brain agentic loop."""

import asyncio
from typing import Any

from docketeer.brain import Brain, ProcessCallbacks
from docketeer.prompt import MessageContent

from ..conftest import FakeMessage, make_text_block, make_tool_use_block


async def _capture(texts: list[str], text: str) -> None:
    texts.append(text)


async def test_on_text_suppressed_on_intermediate_tool_round(
    brain: Brain, fake_messages: Any
):
    """When a response has both text and tool blocks, the text is suppressed."""
    fake_messages.responses = [
        FakeMessage(
            content=[
                make_text_block(text="Let me check that..."),
                make_tool_use_block(name="list_files", input={"path": ""}),
            ],
        ),
        FakeMessage(content=[make_text_block(text="Here's what I found.")]),
    ]
    texts: list[str] = []
    callbacks = ProcessCallbacks(on_text=lambda text: _capture(texts, text))
    content = MessageContent(username="chris", text="list files")
    response = await brain.process("room1", content, callbacks=callbacks)
    assert texts == []
    assert response.text == "Here's what I found."


async def test_on_text_not_fired_on_text_only_response(
    brain: Brain, fake_messages: Any
):
    """on_text should not fire on the final text-only response."""
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Just a reply.")]),
    ]
    texts: list[str] = []
    callbacks = ProcessCallbacks(on_text=lambda text: _capture(texts, text))
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content, callbacks=callbacks)
    assert texts == []


async def test_on_text_not_fired_when_tool_round_has_no_text(
    brain: Brain, fake_messages: Any
):
    """When a tool round has no text blocks, on_text should not fire."""
    fake_messages.responses = [
        FakeMessage(
            content=[make_tool_use_block(name="list_files", input={"path": ""})],
        ),
        FakeMessage(content=[make_text_block(text="Done!")]),
    ]
    texts: list[str] = []
    callbacks = ProcessCallbacks(on_text=lambda text: _capture(texts, text))
    content = MessageContent(username="chris", text="list files")
    await brain.process("room1", content, callbacks=callbacks)
    assert texts == []


async def test_on_text_suppressed_on_multiple_intermediate_rounds(
    brain: Brain, fake_messages: Any
):
    """Text from intermediate tool rounds is suppressed, not dispatched."""
    fake_messages.responses = [
        FakeMessage(
            content=[
                make_text_block(text="Checking first..."),
                make_tool_use_block(id="t1", name="list_files", input={"path": ""}),
            ],
        ),
        FakeMessage(
            content=[
                make_text_block(text="Now the second..."),
                make_tool_use_block(id="t2", name="list_files", input={"path": ""}),
            ],
        ),
        FakeMessage(content=[make_text_block(text="All done.")]),
    ]
    texts: list[str] = []
    callbacks = ProcessCallbacks(on_text=lambda text: _capture(texts, text))
    content = MessageContent(username="chris", text="do things")
    response = await brain.process("room1", content, callbacks=callbacks)
    assert texts == []
    assert response.text == "All done."


async def test_interrupted_exits_loop_early(brain: Brain, fake_messages: Any):
    """When interrupted is set before the first round, the loop exits immediately."""
    fake_messages.responses = [
        FakeMessage(
            content=[make_tool_use_block(name="list_files", input={"path": ""})],
        ),
        FakeMessage(content=[make_text_block(text="Should not reach this.")]),
    ]
    interrupted = asyncio.Event()
    interrupted.set()
    callbacks = ProcessCallbacks(interrupted=interrupted)
    content = MessageContent(username="chris", text="do stuff")
    response = await brain.process("room1", content, callbacks=callbacks)
    assert response.text == ""


async def test_interrupted_after_first_tool_round(brain: Brain, fake_messages: Any):
    """When interrupted is set during a tool round, the loop exits after that round."""
    interrupted = asyncio.Event()

    async def set_interrupted() -> None:
        interrupted.set()

    fake_messages.responses = [
        FakeMessage(
            content=[
                make_text_block(text="Checking..."),
                make_tool_use_block(id="t1", name="list_files", input={"path": ""}),
            ],
        ),
        FakeMessage(
            content=[
                make_tool_use_block(id="t2", name="list_files", input={"path": ""}),
            ],
        ),
        FakeMessage(content=[make_text_block(text="Should not reach this.")]),
    ]
    callbacks = ProcessCallbacks(on_tool_end=set_interrupted, interrupted=interrupted)
    content = MessageContent(username="chris", text="do stuff")
    response = await brain.process("room1", content, callbacks=callbacks)
    assert response.text == ""


async def test_interrupted_not_set_runs_normally(brain: Brain, fake_messages: Any):
    """When interrupted is never set, the loop runs to completion."""
    interrupted = asyncio.Event()
    fake_messages.responses = [
        FakeMessage(
            content=[make_tool_use_block(name="list_files", input={"path": ""})],
        ),
        FakeMessage(content=[make_text_block(text="All done!")]),
    ]
    callbacks = ProcessCallbacks(interrupted=interrupted)
    content = MessageContent(username="chris", text="do stuff")
    response = await brain.process("room1", content, callbacks=callbacks)
    assert response.text == "All done!"
