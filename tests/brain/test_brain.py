"""Tests for the Brain class."""

from typing import Any
from unittest.mock import MagicMock, patch

from docketeer.brain import Brain
from docketeer.config import Config
from docketeer.prompt import HistoryMessage, MessageContent
from docketeer.tools import ToolContext

from ..conftest import FakeMessage, make_text_block, make_tool_use_block


def test_brain_init_first_run(
    config: Config, tool_context: ToolContext, mock_anthropic: MagicMock
):
    soul = config.workspace_path / "SOUL.md"
    assert not soul.exists()
    Brain(config, tool_context)
    assert soul.exists()
    assert (config.workspace_path / "BOOTSTRAP.md").exists()


def test_brain_init_existing_soul(
    config: Config, tool_context: ToolContext, mock_anthropic: MagicMock
):
    (config.workspace_path / "SOUL.md").write_text("custom")
    Brain(config, tool_context)
    assert (config.workspace_path / "SOUL.md").read_text() == "custom"
    assert not (config.workspace_path / "BOOTSTRAP.md").exists()


def test_brain_init_builds_person_map(brain: Brain):
    people = brain.config.workspace_path / "people" / "chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("**Username:** @cguidry")
    brain.rebuild_person_map()
    assert "cguidry" in brain._person_map


def test_rebuild_person_map(brain: Brain):
    assert brain._person_map == {}
    people = brain.config.workspace_path / "people" / "alex"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("**Username:** @alex")
    brain.rebuild_person_map()
    assert "alex" in brain._person_map


def test_load_history_user_messages(brain: Brain):
    msgs = [
        HistoryMessage(
            role="user", username="chris", text="hello", timestamp="2026-02-06 10:00"
        )
    ]
    count = brain.load_history("room1", msgs)
    assert count == 1
    assert (
        "[2026-02-06 10:00] @chris: hello"
        in brain._conversations["room1"][0]["content"]
    )


def test_load_history_assistant_messages(brain: Brain):
    msgs = [HistoryMessage(role="assistant", username="nix", text="hi there")]
    brain.load_history("room1", msgs)
    assert brain._conversations["room1"][0]["content"] == "hi there"


def test_load_history_no_timestamp(brain: Brain):
    msgs = [HistoryMessage(role="user", username="chris", text="hey")]
    brain.load_history("room1", msgs)
    assert brain._conversations["room1"][0]["content"] == "@chris: hey"


def test_has_history(brain: Brain):
    assert not brain.has_history("room1")
    brain.load_history("room1", [HistoryMessage(role="user", username="x", text="y")])
    assert brain.has_history("room1")


def test_build_content_text_only(brain: Brain):
    content = MessageContent(
        username="chris", text="hello", timestamp="2026-02-06 10:00"
    )
    result = brain._build_content(content)
    assert isinstance(result, str)
    assert "[2026-02-06 10:00] @chris: hello" in result


def test_build_content_with_images(brain: Brain):
    content = MessageContent(
        username="chris",
        text="check this",
        images=[("image/png", b"\x89PNG")],
    )
    result = brain._build_content(content)
    assert isinstance(result, list)
    assert any(b.get("type") == "image" for b in result)
    assert any(b.get("type") == "text" for b in result)


def test_build_content_empty_message(brain: Brain):
    content = MessageContent(username="chris", text="")
    result = brain._build_content(content)
    assert isinstance(result, str)
    assert "(empty message)" in result


def test_build_content_images_only(brain: Brain):
    content = MessageContent(username="chris", images=[("image/png", b"\x89PNG")])
    result = brain._build_content(content)
    assert isinstance(result, list)
    assert any(b.get("type") == "image" for b in result)


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


async def test_process_triggers_compaction(brain: Brain, fake_messages: Any):
    brain._room_token_counts["room1"] = 150_000
    for i in range(10):
        brain._conversations["room1"].append(
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
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
    with patch("docketeer.brain.MAX_TOOL_ROUNDS", 3):
        response = await brain.process("room1", content)
    assert response.text == "(no response)"


async def test_process_multi_tool_results_in_history(brain: Brain, fake_messages: Any):
    """Messages with multiple tool_result blocks exercise the cache-strip inner loop."""
    brain._conversations["room1"] = [
        {
            "role": "assistant",
            "content": [make_tool_use_block(id="t1", name="list_files", input={})],
        },
        {
            "role": "user",
            "content": [
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
        },
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
    with patch("docketeer.brain.registry.definitions", return_value=[]):
        response = await brain.process("room1", content)
    assert response.text == "No tools!"


async def test_compact_history_few_messages(brain: Brain, fake_messages: Any):
    brain._conversations["room1"] = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
    ]
    await brain._compact_history("room1", [], [])
    assert len(brain._conversations["room1"]) == 2


async def test_compact_history_empty_transcript(brain: Brain, fake_messages: Any):
    brain._conversations["room1"] = [
        {"role": "user", "content": [{"type": "image", "source": {}}]},
    ] * 10
    await brain._compact_history("room1", [], [])
    assert len(brain._conversations["room1"]) == 10


async def test_compact_history_success(brain: Brain, fake_messages: Any):
    for i in range(12):
        brain._conversations["room1"].append(
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        )
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Conversation summary")])
    ]
    await brain._compact_history("room1", [], [])
    msgs = brain._conversations["room1"]
    assert msgs[0]["content"].startswith("[Earlier conversation summary]")
    assert msgs[1]["content"] == "Got it, I have that context."


async def test_compact_history_summarization_failure(brain: Brain, fake_messages: Any):
    for i in range(12):
        brain._conversations["room1"].append(
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        )
    fake_messages.create = MagicMock(side_effect=Exception("API error"))
    await brain._compact_history("room1", [], [])
    assert len(brain._conversations["room1"]) == 6
