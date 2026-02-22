"""Tests for build_reply in the agentic loop."""

from unittest.mock import MagicMock

from docketeer_deepinfra.loop import build_reply

from .conftest import make_response


def test_basic_content():
    assert build_reply(make_response(content="Hello world"), False, 1) == "Hello world"


def test_empty_content_with_tool_use():
    result = build_reply(make_response(finish_reason="tool_calls"), True, 1)
    assert "I ran the tool" in result


def test_empty_content_without_tool_use():
    assert build_reply(make_response(), False, 1) == "(no response)"


def test_no_choices():
    resp = MagicMock()
    resp.choices = []
    assert build_reply(resp, False, 1) == "(no response)"


def test_truncated_with_tool_use_no_suffix():
    assert (
        build_reply(make_response(content="Hello", finish_reason="length"), True, 1)
        == "Hello"
    )


def test_truncated_without_tool_use_adds_suffix():
    result = build_reply(
        make_response(content="Hello", finish_reason="length"), False, 1
    )
    assert "Hello" in result
    assert "length limit" in result
