"""Tests for claude_code_output: parsing, error handling, and format_prompt."""

import json

import pytest

from docketeer.brain.backend import BackendAuthError, BackendError, ContextTooLargeError
from docketeer.brain.claude_code_output import (
    check_error,
    check_process_exit,
    extract_text,
    format_prompt,
    parse_response,
)

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


# -- format_prompt --


def test_format_prompt_single_message():
    messages = [{"role": "user", "content": "[21:19] @peps: hello"}]
    assert format_prompt(messages) == "[21:19] @peps: hello"


def test_format_prompt_includes_history_for_new_session():
    messages = [
        {"role": "user", "content": "[21:10] @peps: first message"},
        {"role": "assistant", "content": "Got it."},
        {"role": "user", "content": "[21:15] @peps: second message"},
        {"role": "assistant", "content": "Sure thing."},
        {"role": "user", "content": "[21:19] @peps: latest question"},
    ]
    result = format_prompt(messages)
    assert "[21:10] @peps: first message" in result
    assert "[assistant] Got it." in result
    assert "[21:15] @peps: second message" in result
    assert "[assistant] Sure thing." in result
    assert "[21:19] @peps: latest question" in result


def test_format_prompt_resume_sends_only_latest():
    messages = [
        {"role": "user", "content": "[21:10] @peps: old message"},
        {"role": "assistant", "content": "Old reply."},
        {"role": "user", "content": "[21:19] @peps: new message"},
    ]
    result = format_prompt(messages, resume=True)
    assert result == "[21:19] @peps: new message"


def test_format_prompt_empty_messages():
    assert format_prompt([]) == ""


def test_format_prompt_skips_empty_content():
    messages = [
        {"role": "user", "content": ""},
        {"role": "user", "content": "[21:19] @peps: hello"},
    ]
    result = format_prompt(messages)
    assert result == "[21:19] @peps: hello"


# -- parse_response --


def test_parse_response_text_and_session():
    result_dict = {"type": "result", "session_id": "sess-42"}
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
        json.dumps(result_dict),
    ]
    text, session_id, result_event = parse_response(lines)
    assert text == "Hello \n\nworld!"
    assert session_id == "sess-42"
    assert result_event == result_dict


def test_parse_response_no_session():
    result_dict = {"type": "result"}
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            }
        ),
        json.dumps(result_dict),
    ]
    assert parse_response(lines) == ("hi", None, result_dict)


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
    result_dict = {"type": "result", "session_id": "s1"}
    lines = ["not json", "", json.dumps(result_dict)]
    assert parse_response(lines) == ("", "s1", result_dict)


def test_parse_response_empty():
    assert parse_response([]) == ("", None, None)


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


# -- check_process_exit --


def test_check_process_exit_success():
    """Successful exit (code 0) doesn't raise."""
    check_process_exit(0, b"")


def test_check_process_exit_success_with_stderr():
    """Successful exit with stderr doesn't raise (just logs)."""
    check_process_exit(0, b"some warning")


def test_check_process_exit_failure():
    """Non-zero exit raises BackendError."""
    with pytest.raises(BackendError):
        check_process_exit(1, b"something went wrong")


def test_check_process_exit_auth_error():
    """Auth-related stderr raises BackendAuthError."""
    with pytest.raises(BackendAuthError):
        check_process_exit(1, b"unauthorized")
