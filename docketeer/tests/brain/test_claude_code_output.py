"""Tests for claude_code_output: parsing and error handling."""

import json

import pytest

from docketeer.brain.backend import BackendAuthError, BackendError, ContextTooLargeError
from docketeer.brain.claude_code_output import check_error, extract_text, parse_response

# -- extract_text --


def test_extract_text_string_content():
    assert extract_text({"content": "hello"}) == "hello"


def test_extract_text_list_content():
    msg = {
        "content": [
            {"type": "text", "text": "line 1"},
            {"type": "text", "text": "line 2"},
        ]
    }
    assert extract_text(msg) == "line 1\nline 2"


def test_extract_text_skips_non_text_blocks():
    msg = {
        "content": [
            {"type": "image", "source": {}},
            {"type": "text", "text": "visible"},
        ]
    }
    assert extract_text(msg) == "visible"


def test_extract_text_raw_strings_in_list():
    assert extract_text({"content": ["hello", "world"]}) == "hello\nworld"


def test_extract_text_empty():
    assert extract_text({}) == ""


# -- parse_response --


def test_parse_response_text_and_session():
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Hello "}]},
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "world!"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "sess-42"}),
    ]
    text, session_id = parse_response(lines)
    assert text == "Hello \n\nworld!"
    assert session_id == "sess-42"


def test_parse_response_no_session():
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            }
        ),
        json.dumps({"type": "result"}),
    ]
    assert parse_response(lines) == ("hi", None)


def test_parse_response_skips_tool_use():
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Let me check. "},
                        {"type": "tool_use", "name": "search", "input": {}},
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Done!"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    assert parse_response(lines)[0] == "Let me check. \n\nDone!"


def test_parse_response_skips_tool_only_turn():
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "search", "input": {}}]
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Found it!"}]},
            }
        ),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]
    assert parse_response(lines)[0] == "Found it!"


def test_parse_response_malformed_json():
    lines = ["not json", "", json.dumps({"type": "result", "session_id": "s1"})]
    assert parse_response(lines) == ("", "s1")


def test_parse_response_empty():
    assert parse_response([]) == ("", None)


# -- check_error --


@pytest.mark.parametrize("stderr", ["unauthorized", "invalid token", "auth failure"])
def test_check_error_auth(stderr: str):
    with pytest.raises(BackendAuthError):
        check_error(stderr, 1)


def test_check_error_context():
    with pytest.raises(ContextTooLargeError):
        check_error("context window too large", 1)


def test_check_error_generic():
    with pytest.raises(BackendError):
        check_error("something went wrong", 1)
