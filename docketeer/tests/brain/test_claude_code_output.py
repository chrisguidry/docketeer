"""Tests for claude_code_output: parsing and error handling."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from docketeer.brain.backend import BackendAuthError, BackendError, ContextTooLargeError
from docketeer.brain.claude_code_output import (
    check_error,
    check_process_exit,
    extract_text,
    parse_response,
    stream_response,
)
from docketeer.brain.core import ProcessCallbacks

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


# -- stream_response helpers --


def _make_stream(lines: list[str]) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    for line in lines:
        reader.feed_data((line + "\n").encode())
    reader.feed_eof()
    return reader


def _assistant_event(
    text: str | None = None,
    tool_use: bool = False,
) -> str:
    content: list[dict] = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool_use:
        content.append({"type": "tool_use", "name": "search", "input": {}})
    return json.dumps({"type": "assistant", "message": {"content": content}})


def _result_event(session_id: str | None = None) -> str:
    event: dict = {"type": "result"}
    if session_id:
        event["session_id"] = session_id
    return json.dumps(event)


def _callbacks() -> tuple[ProcessCallbacks, dict[str, list]]:
    calls: dict[str, list] = {
        "on_first_text": [],
        "on_text": [],
        "on_tool_start": [],
        "on_tool_end": [],
    }

    async def on_first_text() -> None:
        calls["on_first_text"].append(True)

    async def on_text(text: str) -> None:
        calls["on_text"].append(text)

    async def on_tool_start() -> None:
        calls["on_tool_start"].append(True)

    async def on_tool_end() -> None:
        calls["on_tool_end"].append(True)

    cb = ProcessCallbacks(
        on_first_text=on_first_text,
        on_text=on_text,
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
    )
    return cb, calls


# -- stream_response --


async def test_stream_response_single_text_turn():
    """A single text-only turn is returned as the final text, no callbacks."""
    cb, calls = _callbacks()
    stream = _make_stream([_assistant_event("Hello!"), _result_event("sess-1")])
    text, session_id, result_event = await stream_response(stream, cb)
    assert text == "Hello!"
    assert session_id == "sess-1"
    assert result_event is not None
    assert result_event["session_id"] == "sess-1"
    assert calls["on_first_text"] == [True]
    assert calls["on_text"] == []
    assert calls["on_tool_start"] == []
    assert calls["on_tool_end"] == []


async def test_stream_response_multi_turn_with_tool_use():
    """Intermediate text+tool_use turns fire on_text, final text is returned."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _assistant_event("Let me check.", tool_use=True),
            _assistant_event("Here's what I found."),
            _result_event("sess-2"),
        ]
    )
    text, session_id, _ = await stream_response(stream, cb)
    assert text == "Here's what I found."
    assert session_id == "sess-2"
    assert calls["on_first_text"] == [True]
    assert calls["on_text"] == ["Let me check."]
    assert calls["on_tool_start"] == [True]
    assert calls["on_tool_end"] == [True]


async def test_stream_response_tool_only_turn():
    """A tool_use turn with no text doesn't fire on_text."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _assistant_event(tool_use=True),
            _assistant_event("Result."),
            _result_event("sess-3"),
        ]
    )
    text, session_id, _ = await stream_response(stream, cb)
    assert text == "Result."
    assert calls["on_text"] == []
    assert calls["on_tool_start"] == [True]
    assert calls["on_tool_end"] == [True]


async def test_stream_response_consecutive_tool_rounds():
    """on_tool_end fires between consecutive tool rounds."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _assistant_event("First thought.", tool_use=True),
            _assistant_event("Second thought.", tool_use=True),
            _assistant_event("Done."),
            _result_event("sess-4"),
        ]
    )
    text, session_id, _ = await stream_response(stream, cb)
    assert text == "Done."
    assert calls["on_first_text"] == [True]
    assert calls["on_text"] == ["First thought.", "Second thought."]
    assert calls["on_tool_start"] == [True, True]
    assert calls["on_tool_end"] == [True, True]


async def test_stream_response_no_callbacks():
    """Works fine without callbacks — just returns final text."""
    stream = _make_stream(
        [
            _assistant_event("Let me check.", tool_use=True),
            _assistant_event("Done."),
            _result_event("sess-5"),
        ]
    )
    text, session_id, _ = await stream_response(stream, None)
    assert text == "Done."
    assert session_id == "sess-5"


async def test_stream_response_session_id_extraction():
    """Session ID comes from the result event."""
    stream = _make_stream(
        [
            _assistant_event("Hi."),
            _result_event("my-session-id"),
        ]
    )
    _, session_id, _ = await stream_response(stream)
    assert session_id == "my-session-id"


async def test_stream_response_no_session_id():
    """No session_id in result event returns None."""
    stream = _make_stream(
        [
            _assistant_event("Hi."),
            _result_event(),
        ]
    )
    _, session_id, _ = await stream_response(stream)
    assert session_id is None


async def test_stream_response_malformed_json():
    """Malformed JSON lines are skipped."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            "not json",
            "",
            _assistant_event("Hello."),
            _result_event("sess-6"),
        ]
    )
    text, session_id, _ = await stream_response(stream, cb)
    assert text == "Hello."
    assert session_id == "sess-6"


async def test_stream_response_empty_stream():
    """Empty stream returns empty text and no session ID."""
    stream = _make_stream([])
    text, session_id, result_event = await stream_response(stream)
    assert text == ""
    assert session_id is None
    assert result_event is None


async def test_stream_response_text_tool_text_tool_text():
    """Complex multi-turn: text+tool, text+tool, text — intermediate texts dispatched."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _assistant_event("Step 1.", tool_use=True),
            _assistant_event("Step 2.", tool_use=True),
            _assistant_event("Final answer."),
            _result_event("sess-7"),
        ]
    )
    text, session_id, _ = await stream_response(stream, cb)
    assert text == "Final answer."
    assert calls["on_text"] == ["Step 1.", "Step 2."]
    assert calls["on_tool_start"] == [True, True]
    assert calls["on_tool_end"] == [True, True]


async def test_stream_response_consecutive_text_only_turns():
    """When two text-only turns appear, first is dispatched as intermediate."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _assistant_event("First thought."),
            _assistant_event("Second thought."),
            _result_event("sess-8"),
        ]
    )
    text, session_id, _ = await stream_response(stream, cb)
    assert text == "Second thought."
    assert calls["on_first_text"] == [True]
    assert calls["on_text"] == ["First thought."]


async def test_stream_response_consecutive_text_only_turns_no_callbacks():
    """Consecutive text-only turns without callbacks still returns final text."""
    stream = _make_stream(
        [
            _assistant_event("First thought."),
            _assistant_event("Second thought."),
            _result_event("sess-9"),
        ]
    )
    text, session_id, _ = await stream_response(stream, None)
    assert text == "Second thought."


# -- check_process_exit --


def test_check_process_exit_success():
    """Successful exit (code 0) doesn't raise."""
    proc = AsyncMock()
    proc.returncode = 0
    check_process_exit(proc, b"")


def test_check_process_exit_success_with_stderr():
    """Successful exit with stderr doesn't raise (just logs)."""
    proc = AsyncMock()
    proc.returncode = 0
    check_process_exit(proc, b"some warning")


def test_check_process_exit_failure():
    """Non-zero exit raises BackendError."""
    proc = AsyncMock()
    proc.returncode = 1
    with pytest.raises(BackendError):
        check_process_exit(proc, b"something went wrong")


def test_check_process_exit_auth_error():
    """Auth-related stderr raises BackendAuthError."""
    proc = AsyncMock()
    proc.returncode = 1
    with pytest.raises(BackendAuthError):
        check_process_exit(proc, b"unauthorized")
