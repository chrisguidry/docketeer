"""Tests for stream_response: streaming callbacks and event handling."""

import asyncio
import json

from docketeer.brain.claude_code_output import stream_response
from docketeer.brain.core import ProcessCallbacks

# -- helpers --


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

    async def on_tool_start(tool_name: str) -> None:
        calls["on_tool_start"].append(tool_name)

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
    """Text from tool_use turns is dispatched via on_text, final text is returned."""
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
    assert calls["on_tool_start"] == ["search"]
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
    assert calls["on_tool_start"] == ["search"]
    assert calls["on_tool_end"] == [True]


async def test_stream_response_consecutive_tool_rounds():
    """on_tool_end fires between consecutive tool rounds, text is dispatched."""
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
    assert calls["on_tool_start"] == ["search", "search"]
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
    """Complex multi-turn: text+tool, text+tool, text — all text dispatched."""
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
    assert calls["on_tool_start"] == ["search", "search"]
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


async def test_stream_response_text_turn_before_tool_turn_dispatched():
    """A text-only turn before a tool turn is dispatched via on_text."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _assistant_event("Let me search for that."),
            _assistant_event(tool_use=True),
            _assistant_event("Here's what I found."),
            _result_event("sess-text-before-tool"),
        ]
    )
    text, session_id, _ = await stream_response(stream, cb)
    assert text == "Here's what I found."
    assert calls["on_first_text"] == [True]
    assert calls["on_text"] == ["Let me search for that."]
    assert calls["on_tool_start"] == ["search"]
    assert calls["on_tool_end"] == [True]


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


# -- stream_event handling --


def _stream_event(inner_type: str, **kwargs: object) -> str:
    """Build a stream_event JSON line wrapping an inner API event."""
    inner: dict = {"type": inner_type, **kwargs}
    return json.dumps({"type": "stream_event", "event": inner})


def _text_delta_event(text: str) -> str:
    return _stream_event(
        "content_block_delta",
        delta={"type": "text_delta", "text": text},
    )


def _tool_use_start_event(name: str = "Read") -> str:
    return _stream_event(
        "content_block_start",
        content_block={"type": "tool_use", "name": name},
    )


def _text_block_start_event() -> str:
    return _stream_event(
        "content_block_start",
        content_block={"type": "text"},
    )


async def test_stream_event_fires_on_first_text_early():
    """stream_event text_delta fires on_first_text before assistant event."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _text_delta_event("He"),
            _text_delta_event("llo"),
            _assistant_event("Hello"),
            _result_event("sess-10"),
        ]
    )
    text, session_id, _ = await stream_response(stream, cb)
    assert text == "Hello"
    assert calls["on_first_text"] == [True]


async def test_stream_event_on_first_text_only_fires_once():
    """Multiple text_delta events only fire on_first_text once."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _text_delta_event("He"),
            _text_delta_event("llo"),
            _text_delta_event(" world"),
            _assistant_event("Hello world"),
            _result_event("sess-11"),
        ]
    )
    await stream_response(stream, cb)
    assert calls["on_first_text"] == [True]


async def test_stream_event_tool_start_end():
    """stream_event content_block_start fires tool start/end callbacks."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _text_delta_event("Let me check."),
            _tool_use_start_event("Read"),
            _text_block_start_event(),
            _text_delta_event("Done."),
            _assistant_event("Let me check.", tool_use=True),
            _assistant_event("Done."),
            _result_event("sess-12"),
        ]
    )
    text, _, _ = await stream_response(stream, cb)
    assert text == "Done."
    assert calls["on_first_text"] == [True]
    assert calls["on_tool_start"] == ["Read"]
    assert calls["on_tool_end"] == [True]


async def test_stream_event_consecutive_tools():
    """Consecutive tool starts fire end/start pairs from stream events."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _text_delta_event("Step 1."),
            _tool_use_start_event("Read"),
            _tool_use_start_event("Grep"),
            _text_block_start_event(),
            _text_delta_event("Done."),
            _assistant_event("Step 1.", tool_use=True),
            _assistant_event("Done."),
            _result_event("sess-13"),
        ]
    )
    text, _, _ = await stream_response(stream, cb)
    assert text == "Done."
    assert calls["on_tool_start"] == ["Read", "Grep"]
    assert calls["on_tool_end"] == [True, True]


async def test_stream_event_assistant_skips_redundant_callbacks():
    """When stream_events fired callbacks, assistant events skip them."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _text_delta_event("Hello"),
            _assistant_event("Hello"),
            _result_event("sess-14"),
        ]
    )
    await stream_response(stream, cb)
    # on_first_text should only fire once despite both stream_event and assistant
    assert calls["on_first_text"] == [True]
    assert calls["on_tool_start"] == []
    assert calls["on_tool_end"] == []


async def test_stream_event_no_callbacks():
    """stream_event handling works fine without callbacks."""
    stream = _make_stream(
        [
            _text_delta_event("Hi"),
            _tool_use_start_event(),
            _text_block_start_event(),
            _assistant_event("Hi", tool_use=True),
            _assistant_event("Done."),
            _result_event("sess-15"),
        ]
    )
    text, session_id, _ = await stream_response(stream, None)
    assert text == "Done."
    assert session_id == "sess-15"


async def test_stream_event_unknown_inner_type_ignored():
    """stream_event with unrecognized inner type is silently skipped."""
    cb, calls = _callbacks()
    stream = _make_stream(
        [
            _stream_event("message_stop"),
            _assistant_event("Hello."),
            _result_event("sess-16"),
        ]
    )
    text, _, _ = await stream_response(stream, cb)
    assert text == "Hello."
    assert calls["on_tool_start"] == []


async def test_stream_event_content_block_start_unknown_type_ignored():
    """content_block_start with unrecognized block type is skipped."""
    cb, calls = _callbacks()
    unknown_block = _stream_event(
        "content_block_start",
        content_block={"type": "image"},
    )
    stream = _make_stream(
        [
            unknown_block,
            _assistant_event("Hello."),
            _result_event("sess-17"),
        ]
    )
    text, _, _ = await stream_response(stream, cb)
    assert text == "Hello."
    assert calls["on_tool_start"] == []
