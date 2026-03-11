"""Tests for the TUI chat client."""

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.chat import IncomingMessage, RoomKind
from docketeer_tui.client import ROOM_ID, TUIClient


def _make_msg() -> IncomingMessage:
    return IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="chris",
        display_name="Chris",
        text="hi",
        room_id=ROOM_ID,
        kind=RoomKind.direct,
        timestamp=datetime.now(UTC),
    )


async def test_context_manager():
    with patch("docketeer_tui.client._patched_stdout", return_value=MagicMock()):
        client = TUIClient()
        async with client:
            assert not client._closed
            assert client._session is not None
        assert client._closed


async def test_send_message_stores_history():
    client = TUIClient()
    await client.send_message("room1", "hello world")
    assert len(client._messages) == 1
    assert client._messages[0].text == "hello world"
    assert client._messages[0].username == client.username


async def test_send_message_with_thread():
    client = TUIClient()
    await client.send_message("room1", "reply", thread_id="t1")
    assert len(client._messages) == 1


async def test_send_message_with_attachments():
    client = TUIClient()
    await client.send_message("room1", "look", attachments=[{"url": "x"}])
    assert len(client._messages) == 1


async def test_upload_file():
    client = TUIClient()
    await client.upload_file("room1", "/tmp/test.txt", message="here")


async def test_upload_file_no_message():
    client = TUIClient()
    await client.upload_file("room1", "/tmp/test.txt")


async def test_upload_file_with_thread():
    client = TUIClient()
    await client.upload_file("room1", "/tmp/test.txt", thread_id="t1")


async def test_fetch_attachment_raises():
    client = TUIClient()
    with pytest.raises(ConnectionError, match="TUI client cannot fetch attachments"):
        await client.fetch_attachment("http://example.com/file.png")


async def test_fetch_message_found():
    client = TUIClient()
    await client.send_message("room1", "test msg")
    msg_id = client._messages[0].message_id
    result = await client.fetch_message(msg_id)
    assert result is not None
    assert result["msg"] == "test msg"


async def test_fetch_message_not_found():
    client = TUIClient()
    await client.send_message("room1", "something")
    result = await client.fetch_message("nonexistent")
    assert result is None


async def test_fetch_messages_returns_history():
    client = TUIClient()
    await client.send_message("room1", "one")
    await client.send_message("room1", "two")
    messages = await client.fetch_messages(ROOM_ID)
    assert len(messages) == 2


async def test_fetch_messages_respects_count():
    client = TUIClient()
    for i in range(5):
        await client.send_message("room1", f"msg {i}")
    messages = await client.fetch_messages(ROOM_ID, count=2)
    assert len(messages) == 2
    assert messages[-1].text == "msg 4"


async def test_fetch_messages_time_filters():
    client = TUIClient()
    await client.send_message("room1", "old")
    t = datetime.now(UTC)
    await client.send_message("room1", "new")

    after_msgs = await client.fetch_messages(ROOM_ID, after=t)
    assert all(m.text == "new" for m in after_msgs)

    before_msgs = await client.fetch_messages(ROOM_ID, before=t)
    assert all(m.text == "old" for m in before_msgs)


async def test_list_rooms():
    client = TUIClient()
    rooms = await client.list_rooms()
    assert len(rooms) == 1
    assert rooms[0].room_id == ROOM_ID
    assert rooms[0].kind is RoomKind.direct


async def test_room_context():
    client = TUIClient()
    ctx = await client.room_context(ROOM_ID, "chris")
    assert ctx == "Room: DM with @chris"


async def test_set_status_away():
    client = TUIClient()
    await client.set_status("away")


async def test_set_status_online():
    client = TUIClient()
    await client.set_status("online")


async def test_set_status_with_message():
    client = TUIClient()
    await client.set_status("busy", "working")


async def test_send_typing_is_noop():
    client = TUIClient()
    await client.send_typing("room1", True)
    await client.send_typing("room1", False)


async def test_react():
    client = TUIClient()
    await client.react("msg1", ":thumbsup:")
    assert client._reactions_printed
    await client.react("msg1", ":brain:")
    assert len(client._reaction_emojis) == 2
    client._stop_reactions()
    assert len(client._reaction_emojis) == 0
    assert not client._reactions_printed


async def test_unreact():
    client = TUIClient()
    await client.unreact("msg1", ":thumbsup:")


async def test_incoming_messages_yields_input():
    client = TUIClient()
    with patch.object(client, "_read_input", AsyncMock(side_effect=["hello", None])):
        messages = []
        async for msg in client.incoming_messages():
            messages.append(msg)
    assert len(messages) == 1
    assert messages[0].text == "hello"
    assert messages[0].room_id == ROOM_ID
    assert messages[0].username == client._human_username
    assert messages[0].kind is RoomKind.direct


async def test_incoming_messages_skips_blank():
    client = TUIClient()
    with patch.object(
        client, "_read_input", AsyncMock(side_effect=["", "  ", "actual", None])
    ):
        messages = []
        async for msg in client.incoming_messages():
            messages.append(msg)
    assert len(messages) == 1
    assert messages[0].text == "actual"


async def test_incoming_messages_stores_history():
    client = TUIClient()
    with patch.object(client, "_read_input", AsyncMock(side_effect=["hello", None])):
        async for _ in client.incoming_messages():
            pass
    assert len(client._messages) == 1
    assert client._messages[0].username == client._human_username


async def test_incoming_messages_eof():
    client = TUIClient()
    with patch.object(client, "_read_input", AsyncMock(side_effect=EOFError)):
        messages = []
        async for (
            msg
        ) in client.incoming_messages():  # pragma: no branch - never iterates
            messages.append(msg)  # pragma: no cover
    assert len(messages) == 0


async def test_incoming_messages_keyboard_interrupt():
    client = TUIClient()
    with patch.object(client, "_read_input", AsyncMock(side_effect=KeyboardInterrupt)):
        messages = []
        async for (
            msg
        ) in client.incoming_messages():  # pragma: no branch - never iterates
            messages.append(msg)  # pragma: no cover
    assert len(messages) == 0


async def test_read_input_eof():
    client = TUIClient()
    mock_session = AsyncMock()
    mock_session.prompt_async = AsyncMock(side_effect=EOFError)
    client._session = mock_session
    assert await client._read_input() is None


async def test_read_input_returns_text():
    client = TUIClient()
    mock_session = AsyncMock()
    mock_session.prompt_async = AsyncMock(return_value="hello")
    client._session = mock_session
    assert await client._read_input() == "hello"


async def test_incoming_messages_closed():
    client = TUIClient()
    client._closed = True
    messages = []
    async for msg in client.incoming_messages():  # pragma: no branch - never iterates
        messages.append(msg)  # pragma: no cover
    assert len(messages) == 0


async def test_set_status_debug_logging(caplog: pytest.LogCaptureFixture):
    client = TUIClient()
    with caplog.at_level(logging.DEBUG, logger="docketeer_tui.client"):
        await client.set_status("online", "ready")
    assert "status: online ready" in caplog.text


def test_patched_stdout():
    from docketeer_tui.client import _patched_stdout

    with _patched_stdout():
        pass


async def test_aexit_without_aenter():
    """__aexit__ should not fail if __aenter__ was never called."""
    client = TUIClient()
    await client.__aexit__(None, None, None)
    assert client._closed


def test_create_client():
    from docketeer_tui import create_client

    client = create_client()
    assert isinstance(client, TUIClient)


def test_username_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCKETEER_TUI_USERNAME", "cguidry")
    client = TUIClient()
    assert client._human_username == "cguidry"
    assert client._human_user_id == "tui-cguidry"


def test_username_defaults_to_os_user():
    import getpass

    client = TUIClient()
    assert client._human_username == getpass.getuser()


async def test_room_slug():
    client = TUIClient()
    slug = await client.room_slug(ROOM_ID)
    assert slug == client._human_username


async def test_send_message_calls_on_message_sent_callback():
    client = TUIClient()
    calls: list[tuple[str, str]] = []

    async def recorder(room_id: str, text: str) -> None:
        calls.append((room_id, text))

    client._on_message_sent = recorder
    await client.send_message("room1", "hello")
    assert calls == [("room1", "hello")]


async def test_start_reply_stream_returns_handle():
    client = TUIClient()
    stream = await client.start_reply_stream(_make_msg(), "t1", "Hello")
    assert stream is not None
    assert stream.parts == ["Hello"]
    assert stream.lines_printed == 0


async def test_append_reply_stream_accumulates_text():
    client = TUIClient()
    stream = await client.start_reply_stream(_make_msg(), "t1", "He")
    assert stream is not None
    await client.append_reply_stream(stream, "llo")
    assert stream.parts == ["He", "llo"]
    assert stream.lines_printed > 0


async def test_append_reply_stream_reprints_existing():
    client = TUIClient()
    stream = await client.start_reply_stream(_make_msg(), "t1", "He")
    assert stream is not None
    await client.append_reply_stream(stream, "llo")
    first_lines = stream.lines_printed
    await client.append_reply_stream(stream, " world")
    assert stream.parts == ["He", "llo", " world"]
    assert stream.lines_printed >= first_lines


async def test_stop_reply_stream_stores_message():
    client = TUIClient()
    stream = await client.start_reply_stream(_make_msg(), "t1", "Hello ")
    assert stream is not None
    await client.append_reply_stream(stream, "world")
    await client.stop_reply_stream(stream)
    assert len(client._messages) == 1
    assert client._messages[0].text == "Hello world"


async def test_stop_reply_stream_calls_on_message_sent():
    client = TUIClient()
    calls: list[tuple[str, str]] = []

    async def recorder(room_id: str, text: str) -> None:
        calls.append((room_id, text))

    client._on_message_sent = recorder
    stream = await client.start_reply_stream(_make_msg(), "t1", "done")
    assert stream is not None
    await client.stop_reply_stream(stream)
    assert calls == [(ROOM_ID, "done")]


def test_reprint_stream_panel_no_prior_output():
    from docketeer_tui.client import _TUIStream

    client = TUIClient()
    stream = _TUIStream()
    stream.parts.append("hello")
    client._reprint_stream_panel(stream)
    assert stream.lines_printed > 0


async def test_react_during_streaming_tracks_extra_lines():
    client = TUIClient()
    stream = await client.start_reply_stream(_make_msg(), "t1", "thinking...")
    assert stream is not None
    assert stream.extra_lines == 0

    # First append prints the panel
    await client.append_reply_stream(stream, "...")
    assert stream.lines_printed > 0

    await client.react("m1", ":globe_with_meridians:")
    assert stream.extra_lines == 1

    # Second react on same line (reactions_printed=True) doesn't add extra
    await client.react("m1", ":brain:")
    assert stream.extra_lines == 1

    # Reprint clears extra lines
    await client.append_reply_stream(stream, " done")
    assert stream.extra_lines == 0


async def test_start_reply_stream_clears_reactions():
    client = TUIClient()
    await client.react("m1", ":brain:")
    assert client._reactions_printed
    stream = await client.start_reply_stream(_make_msg(), "t1", "hi")
    assert stream is not None
    assert not client._reactions_printed
