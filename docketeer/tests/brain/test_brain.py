"""Tests for the Brain class."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.brain import Brain, ProcessCallbacks
from docketeer.chat import RoomMessage
from docketeer.prompt import (
    Base64ImageSourceParam,
    ImageBlockParam,
    MessageContent,
    MessageParam,
)
from docketeer.tools import ToolContext

from ..conftest import FakeMessage, make_text_block, make_tool_use_block


def test_brain_init_wires_summarize_callback(
    tool_context: ToolContext, mock_anthropic: MagicMock
):
    assert tool_context.summarize is None
    Brain(tool_context)
    assert tool_context.summarize is not None
    assert callable(tool_context.summarize)


def test_brain_init_wires_classify_response_callback(
    tool_context: ToolContext, mock_anthropic: MagicMock
):
    assert tool_context.classify_response is None
    Brain(tool_context)
    assert tool_context.classify_response is not None
    assert callable(tool_context.classify_response)


def test_brain_init_first_run(tool_context: ToolContext, mock_anthropic: MagicMock):
    soul = tool_context.workspace / "SOUL.md"
    assert not soul.exists()
    Brain(tool_context)
    assert soul.exists()
    assert (tool_context.workspace / "BOOTSTRAP.md").exists()


def test_brain_init_seeds_practice_md(
    tool_context: ToolContext, mock_anthropic: MagicMock
):
    Brain(tool_context)
    assert (tool_context.workspace / "PRACTICE.md").exists()


def test_brain_init_existing_soul(tool_context: ToolContext, mock_anthropic: MagicMock):
    (tool_context.workspace / "SOUL.md").write_text("custom")
    Brain(tool_context)
    assert (tool_context.workspace / "SOUL.md").read_text() == "custom"
    assert not (tool_context.workspace / "BOOTSTRAP.md").exists()


async def test_brain_async_context_manager(
    tool_context: ToolContext, mock_anthropic: MagicMock
):
    async with Brain(tool_context) as brain:
        assert isinstance(brain, Brain)


def test_load_history_user_messages(brain: Brain):
    msgs = [
        RoomMessage(
            message_id="m1",
            timestamp=datetime(2026, 2, 6, 15, 0, tzinfo=UTC),
            username="chris",
            display_name="Chris",
            text="hello",
        )
    ]
    count = brain.load_history("room1", msgs)
    assert count == 1
    conv = brain._conversations["room1"][0].content
    assert "@chris: hello" in conv
    assert "2026-02-06" in conv


def test_load_history_assistant_messages(brain: Brain):
    brain.tool_context.agent_username = "nix"
    msgs = [
        RoomMessage(
            message_id="m1",
            timestamp=datetime(2026, 2, 6, 15, 0, tzinfo=UTC),
            username="nix",
            display_name="Nix",
            text="hi there",
        )
    ]
    brain.load_history("room1", msgs)
    assert brain._conversations["room1"][0].content == "hi there"


def test_has_history(brain: Brain):
    assert not brain.has_history("room1")
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m1",
                timestamp=datetime(2026, 2, 6, 15, 0, tzinfo=UTC),
                username="x",
                display_name="X",
                text="y",
            )
        ],
    )
    assert brain.has_history("room1")


def test_build_content_text_only(brain: Brain):
    content = MessageContent(
        username="chris",
        text="hello",
        timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
    )
    result = brain._build_content(content)
    assert isinstance(result, str)
    assert "@chris: hello" in result


def test_build_content_with_images(brain: Brain):
    content = MessageContent(
        username="chris",
        text="check this",
        images=[("image/png", b"\x89PNG")],
    )
    result = brain._build_content(content)
    assert isinstance(result, list)
    assert any(b.type == "image" for b in result)
    assert any(b.type == "text" for b in result)


def test_build_content_empty_message(brain: Brain):
    content = MessageContent(username="chris", text="")
    result = brain._build_content(content)
    assert isinstance(result, str)
    assert "(empty message)" in result


def test_build_content_images_only(brain: Brain):
    content = MessageContent(username="chris", images=[("image/png", b"\x89PNG")])
    result = brain._build_content(content)
    assert isinstance(result, list)
    assert any(b.type == "image" for b in result)


async def test_process_simple_text_response(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi there!")])]
    content = MessageContent(username="chris", text="hello")
    response = await brain.process("room1", content)
    assert response.text == "Hi there!"


async def test_process_with_tool_use(brain: Brain, fake_messages: Any):
    fake_messages.responses = [
        FakeMessage(
            content=[make_tool_use_block(name="list_files", input={"path": ""})],
            stop_reason="end_turn",
        ),
        FakeMessage(content=[make_text_block(text="Done!")]),
    ]
    content = MessageContent(username="chris", text="list files")
    response = await brain.process("room1", content)
    assert response.text == "Done!"


async def test_process_multi_round_tools(brain: Brain, fake_messages: Any):
    fake_messages.responses = [
        FakeMessage(
            content=[
                make_tool_use_block(id="t1", name="list_files", input={"path": ""})
            ],
            stop_reason="end_turn",
        ),
        FakeMessage(
            content=[
                make_tool_use_block(id="t2", name="list_files", input={"path": ""})
            ],
            stop_reason="end_turn",
        ),
        FakeMessage(content=[make_text_block(text="All done!")]),
    ]
    content = MessageContent(username="chris", text="do stuff")
    response = await brain.process("room1", content)
    assert response.text == "All done!"


async def test_process_max_tokens_truncation(brain: Brain, fake_messages: Any):
    fake_messages.responses = [
        FakeMessage(
            content=[make_text_block(text="partial")],
            stop_reason="max_tokens",
        ),
    ]
    content = MessageContent(username="chris", text="write something long")
    response = await brain.process("room1", content)
    assert "hit my response length limit" in response.text


async def test_process_max_tokens_with_tool_blocks(brain: Brain, fake_messages: Any):
    fake_messages.responses = [
        FakeMessage(
            content=[make_tool_use_block(name="list_files", input={"path": ""})],
            stop_reason="max_tokens",
        ),
        FakeMessage(
            content=[make_text_block(text="recovered")],
            stop_reason="end_turn",
        ),
    ]
    content = MessageContent(username="chris", text="do things")
    response = await brain.process("room1", content)
    assert response.text == "recovered"


async def test_process_empty_response(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[])]
    content = MessageContent(username="chris", text="hello")
    response = await brain.process("room1", content)
    assert response.text == "(no response)"


async def test_process_tool_only_returns_empty(brain: Brain, fake_messages: Any):
    """When Claude uses a tool then returns no text, the response is empty (not posted)."""
    fake_messages.responses = [
        FakeMessage(
            content=[make_tool_use_block(name="journal_add", input={"entry": "hi"})],
        ),
        FakeMessage(content=[]),
    ]
    content = MessageContent(username="chris", text="thanks")
    response = await brain.process("room1", content)
    assert response.text == ""


async def test_process_triggers_compaction(brain: Brain, fake_messages: Any):
    brain._room_token_counts["room1"] = 150_000
    for i in range(10):
        brain._conversations["room1"].append(
            MessageParam(role="user" if i % 2 == 0 else "assistant", content=f"msg {i}")
        )
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Summary here")]),
        FakeMessage(content=[make_text_block(text="Final answer")]),
    ]
    content = MessageContent(username="chris", text="question")
    response = await brain.process("room1", content)
    assert response.text == "Final answer"


async def test_process_exhausts_tool_rounds(brain: Brain, fake_messages: Any):
    """When every round has tool_use, the loop naturally exhausts MAX_TOOL_ROUNDS."""
    fake_messages.responses = [
        FakeMessage(
            content=[
                make_tool_use_block(id=f"t{i}", name="list_files", input={"path": ""})
            ],
            stop_reason="end_turn",
        )
        for i in range(3)
    ]
    content = MessageContent(username="chris", text="keep going")
    with patch("docketeer_anthropic.loop.MAX_TOOL_ROUNDS", 3):
        response = await brain.process("room1", content)
    assert response.text == ""


async def test_process_multi_tool_results_in_history(brain: Brain, fake_messages: Any):
    """Messages with multiple tool_result blocks exercise the cache-strip inner loop."""
    brain._conversations["room1"] = [
        MessageParam(
            role="assistant",
            content=[make_tool_use_block(id="t1", name="list_files", input={})],
        ),
        MessageParam(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "ok",
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": "some context"},
                {
                    "type": "tool_result",
                    "tool_use_id": "t2",
                    "content": "ok2",
                    "cache_control": {"type": "ephemeral"},
                },
            ],
        ),
    ]
    fake_messages.responses = [
        FakeMessage(
            content=[
                make_tool_use_block(id="t3", name="list_files", input={"path": ""})
            ],
            stop_reason="end_turn",
        ),
        FakeMessage(content=[make_text_block(text="Done!")]),
    ]
    content = MessageContent(username="chris", text="continue")
    response = await brain.process("room1", content)
    assert response.text == "Done!"


async def test_process_response_with_multiple_text_blocks(
    brain: Brain, fake_messages: Any
):
    """Response with multiple TextBlocks exercises the reply_parts loop back-edge."""
    fake_messages.responses = [
        FakeMessage(
            content=[make_text_block(text="Part 1"), make_text_block(text="Part 2")]
        ),
    ]
    content = MessageContent(username="chris", text="hello")
    response = await brain.process("room1", content)
    assert "Part 1" in response.text
    assert "Part 2" in response.text


async def test_process_no_tools_registered(brain: Brain, fake_messages: Any):
    """Process works when no tools are registered."""
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="No tools!")])]
    content = MessageContent(username="chris", text="hello")
    with patch("docketeer.brain.core.registry.definitions", return_value=[]):
        response = await brain.process("room1", content)
    assert response.text == "No tools!"


async def test_compact_history_few_messages(brain: Brain, fake_messages: Any):
    brain._conversations["room1"] = [
        MessageParam(role="user", content="hi"),
        MessageParam(role="assistant", content="hey"),
    ]
    await brain._compact_history("room1", [], [], "claude-haiku-4-5-20251001")
    assert len(brain._conversations["room1"]) == 2


async def test_compact_history_empty_transcript(brain: Brain, fake_messages: Any):
    brain._conversations["room1"] = [
        MessageParam(
            role="user",
            content=[
                ImageBlockParam(
                    type="image",
                    source=Base64ImageSourceParam(
                        type="base64",
                        media_type="image/png",
                        data="",
                    ),
                )
            ],
        ),
    ] * 10
    await brain._compact_history("room1", [], [], "claude-haiku-4-5-20251001")
    assert len(brain._conversations["room1"]) == 10


async def test_compact_history_success(brain: Brain, fake_messages: Any):
    for i in range(12):
        role = "user" if i % 2 == 0 else "assistant"
        brain._conversations["room1"].append(
            MessageParam(role=role, content=f"msg {i}")
        )
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Conversation summary")])
    ]
    await brain._compact_history("room1", [], [], "claude-haiku-4-5-20251001")
    msgs = brain._conversations["room1"]
    assert msgs[0].role == "user"
    assert msgs[1].content == "Got it, I have that context."


async def test_compact_history_summarization_failure(brain: Brain, fake_messages: Any):
    for i in range(12):
        role = "user" if i % 2 == 0 else "assistant"
        brain._conversations["room1"].append(
            MessageParam(role=role, content=f"msg {i}")
        )
    fake_messages.create = AsyncMock(side_effect=Exception("API error"))
    await brain._compact_history("room1", [], [], "claude-haiku-4-5-20251001")
    assert len(brain._conversations["room1"]) == 6


async def test_on_first_text_fires_on_text_response(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    on_first_text = AsyncMock()
    callbacks = ProcessCallbacks(on_first_text=on_first_text)
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content, callbacks=callbacks)
    on_first_text.assert_awaited_once()


async def test_on_first_text_not_fired_on_tool_only_round(
    brain: Brain, fake_messages: Any
):
    fake_messages.responses = [
        FakeMessage(
            content=[make_tool_use_block(name="list_files", input={"path": ""})],
        ),
        FakeMessage(content=[make_text_block(text="Done!")]),
    ]
    on_first_text = AsyncMock()
    callbacks = ProcessCallbacks(on_first_text=on_first_text)
    content = MessageContent(username="chris", text="list files")
    await brain.process("room1", content, callbacks=callbacks)
    # on_first_text fires on the second round (text response), not the first (tool-only)
    on_first_text.assert_awaited_once()


async def test_on_tool_start_end_fire_around_tool_execution(
    brain: Brain, fake_messages: Any
):
    fake_messages.responses = [
        FakeMessage(
            content=[make_tool_use_block(name="list_files", input={"path": ""})],
        ),
        FakeMessage(content=[make_text_block(text="Done!")]),
    ]
    on_tool_start = AsyncMock()
    on_tool_end = AsyncMock()
    callbacks = ProcessCallbacks(on_tool_start=on_tool_start, on_tool_end=on_tool_end)
    content = MessageContent(username="chris", text="do stuff")
    await brain.process("room1", content, callbacks=callbacks)
    on_tool_start.assert_awaited_once_with("list_files")
    on_tool_end.assert_awaited_once()


async def test_process_with_no_callbacks(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    response = await brain.process("room1", content, callbacks=None)
    assert response.text == "Hi!"


@pytest.fixture()
def clean_inference_env(monkeypatch: pytest.MonkeyPatch):
    """Fixture that provides clean inference env vars and restores them after."""
    monkeypatch.delenv("DOCKETEER_ANTHROPIC_BACKEND", raising=False)
    monkeypatch.delenv("DOCKETEER_ANTHROPIC_API_KEY", raising=False)
    return monkeypatch


def test_create_backend_loads_inference_plugin(clean_inference_env: pytest.MonkeyPatch):
    """Test that _create_backend loads the inference backend plugin."""
    from docketeer.brain.core import _create_backend

    clean_inference_env.setenv("DOCKETEER_ANTHROPIC_BACKEND", "api")
    clean_inference_env.setenv("DOCKETEER_ANTHROPIC_API_KEY", "test-key")
    backend = _create_backend()
    assert backend is not None


def test_create_backend_raises_when_no_plugin(clean_inference_env: pytest.MonkeyPatch):
    """Test that _create_backend raises RuntimeError when no plugin is installed."""
    from docketeer.brain.core import _create_backend

    with patch("docketeer.brain.core.discover_one", return_value=None):
        with pytest.raises(RuntimeError, match="No inference backend plugin"):
            _create_backend()
