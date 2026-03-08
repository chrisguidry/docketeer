"""Tests for Brain._build_content() JSON metadata prefix."""

import json
from datetime import UTC, datetime

from docketeer.brain import Brain
from docketeer.prompt import MessageContent, TextBlockParam


def test_build_content_text_only(brain: Brain):
    content = MessageContent(
        username="chris",
        text="hello",
        timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
    )
    result = brain._build_content(content)
    assert isinstance(result, str)
    meta_line, message_line = result.split("\n", 1)
    meta = json.loads(meta_line)
    assert "now" in meta
    assert message_line == "@chris: hello"


def test_build_content_with_room_context(brain: Brain):
    content = MessageContent(username="chris", text="hello")
    result = brain._build_content(content, room_context="DM with @alice")
    assert isinstance(result, str)
    meta = json.loads(result.split("\n", 1)[0])
    assert meta["room"] == "DM with @alice"


def test_build_content_with_message_id_and_thread(brain: Brain):
    content = MessageContent(
        username="chris", text="hello", message_id="msg1", thread_id="thr1"
    )
    result = brain._build_content(content)
    assert isinstance(result, str)
    meta = json.loads(result.split("\n", 1)[0])
    assert meta["message_id"] == "msg1"
    assert meta["thread"] == "thr1"


def test_build_content_omits_empty_fields(brain: Brain):
    content = MessageContent(username="chris", text="hello")
    result = brain._build_content(content)
    assert isinstance(result, str)
    meta = json.loads(result.split("\n", 1)[0])
    assert "room" not in meta
    assert "message_id" not in meta
    assert "thread" not in meta


def test_build_content_with_images(brain: Brain):
    content = MessageContent(
        username="chris",
        text="check this",
        images=[("image/png", b"\x89PNG")],
    )
    result = brain._build_content(content)
    assert isinstance(result, list)
    assert any(b.type == "image" for b in result)
    # First block is a text block with JSON meta + message
    text_block = result[0]
    assert isinstance(text_block, TextBlockParam)
    meta_line, message_line = text_block.text.split("\n", 1)
    json.loads(meta_line)  # valid JSON
    assert message_line == "@chris: check this"


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


def test_build_content_no_username(brain: Brain):
    content = MessageContent(text="A signal arrived")
    result = brain._build_content(content)
    assert isinstance(result, str)
    _, message_line = result.split("\n", 1)
    assert message_line == "A signal arrived"


def test_build_content_no_username_empty_text(brain: Brain):
    content = MessageContent()
    result = brain._build_content(content)
    assert isinstance(result, str)
    assert "(empty message)" in result
