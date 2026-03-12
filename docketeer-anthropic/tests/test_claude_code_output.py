"""Tests for claude_code_output: parsing, error handling, and format_prompt."""

import json
from pathlib import Path

import pytest

from docketeer.brain.backend import BackendAuthError, BackendError, ContextTooLargeError
from docketeer.prompt import (
    Base64ImageSourceParam,
    ImageBlockParam,
    MessageParam,
    TextBlockParam,
)
from docketeer_anthropic.claude_code_output import (
    check_error,
    check_process_exit,
    extract_text,
    format_prompt,
    parse_response,
    save_message_images,
)

# -- extract_text --


def test_extract_text_string_content():
    assert extract_text(MessageParam(role="user", content="hello")) == "hello"


def test_extract_text_list_content():
    msg = MessageParam(
        role="user",
        content=[
            {"type": "text", "text": "line 1"},
            {"type": "text", "text": "line 2"},
        ],
    )
    assert extract_text(msg) == "line 1\nline 2"


def test_extract_text_skips_non_text_blocks():
    msg = MessageParam(
        role="user",
        content=[
            {"type": "image", "source": {}},
            {"type": "text", "text": "visible"},
        ],
    )
    assert extract_text(msg) == "visible"


def test_extract_text_raw_strings_in_list():
    msg = MessageParam(role="user", content=["hello", "world"])
    assert extract_text(msg) == "hello\nworld"


def test_extract_text_empty():
    assert extract_text(MessageParam(role="user", content="")) == ""


def test_extract_text_text_block_params():
    msg = MessageParam(
        role="user",
        content=[TextBlockParam(text="hello"), TextBlockParam(text="world")],
    )
    assert extract_text(msg) == "hello\nworld"


def test_extract_text_image_block_placeholder():
    img = ImageBlockParam(
        source=Base64ImageSourceParam(media_type="image/png", data="abc")
    )
    msg = MessageParam(
        role="user",
        content=[TextBlockParam(text="look"), img],
    )
    assert extract_text(msg) == "look\n[image]"


# -- save_message_images --


def test_save_message_images_writes_files(tmp_path: Path):
    import base64

    raw_bytes = b"\x89PNG\r\n\x1a\n"
    encoded = base64.b64encode(raw_bytes).decode()
    img = ImageBlockParam(
        source=Base64ImageSourceParam(media_type="image/png", data=encoded)
    )
    msg = MessageParam(role="user", content=[TextBlockParam(text="hi"), img])

    paths = save_message_images([msg], tmp_path / "images")

    assert len(paths) == 1
    assert paths[0].suffix == ".png"
    assert paths[0].read_bytes() == raw_bytes
    assert isinstance(msg.content[1], TextBlockParam)
    assert str(paths[0]) in msg.content[1].text


def test_save_message_images_no_images(tmp_path: Path):
    msg = MessageParam(role="user", content="just text")
    paths = save_message_images([msg], tmp_path / "images")
    assert paths == []


def test_save_message_images_jpeg_extension(tmp_path: Path):
    import base64

    encoded = base64.b64encode(b"\xff\xd8\xff").decode()
    img = ImageBlockParam(
        source=Base64ImageSourceParam(media_type="image/jpeg", data=encoded)
    )
    msg = MessageParam(role="user", content=[img])

    paths = save_message_images([msg], tmp_path / "images")
    assert paths[0].suffix == ".jpg"


def test_save_message_images_unknown_media_type(tmp_path: Path):
    import base64

    encoded = base64.b64encode(b"\x00").decode()
    img = ImageBlockParam(
        source=Base64ImageSourceParam(media_type="image/tiff", data=encoded)
    )
    msg = MessageParam(role="user", content=[img])

    paths = save_message_images([msg], tmp_path / "images")
    assert paths[0].suffix == ".bin"


# -- format_prompt --


def test_format_prompt_single_message():
    messages = [MessageParam(role="user", content="[21:19] @peps: hello")]
    assert format_prompt(messages) == "[21:19] @peps: hello"


def test_format_prompt_includes_history_for_new_session():
    messages = [
        MessageParam(role="user", content="[21:10] @peps: first message"),
        MessageParam(role="assistant", content="Got it."),
        MessageParam(role="user", content="[21:15] @peps: second message"),
        MessageParam(role="assistant", content="Sure thing."),
        MessageParam(role="user", content="[21:19] @peps: latest question"),
    ]
    result = format_prompt(messages)
    assert "[21:10] @peps: first message" in result
    assert "[assistant] Got it." in result
    assert "[21:15] @peps: second message" in result
    assert "[assistant] Sure thing." in result
    assert "[21:19] @peps: latest question" in result


def test_format_prompt_resume_sends_only_latest():
    messages = [
        MessageParam(role="user", content="[21:10] @peps: old message"),
        MessageParam(role="assistant", content="Old reply."),
        MessageParam(role="user", content="[21:19] @peps: new message"),
    ]
    result = format_prompt(messages, resume=True)
    assert result == "[21:19] @peps: new message"


def test_format_prompt_empty_messages():
    assert format_prompt([]) == ""


def test_format_prompt_skips_empty_content():
    messages = [
        MessageParam(role="user", content=""),
        MessageParam(role="user", content="[21:19] @peps: hello"),
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


@pytest.mark.parametrize("stderr", ["tokenizer error", "author not found"])
def test_check_error_word_boundary_no_false_positive(stderr: str):
    """Words like 'tokenizer' and 'author' should not match 'token' and 'auth'."""
    with pytest.raises(BackendError):
        check_error(stderr, 1)


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
