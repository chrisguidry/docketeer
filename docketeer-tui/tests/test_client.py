"""Tests for the TUI chat client."""

import logging
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer_tui.client import ROOM_ID, USERNAME, TUIClient, _redirect_logs_to_file


@pytest.fixture(autouse=True)
def _isolate_logging() -> Generator[None]:
    """Save and restore root logger handlers around each test."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    yield
    # close any file handlers added during the test
    for handler in root.handlers[:]:
        if handler not in original_handlers:
            handler.close()
            root.removeHandler(handler)
    root.handlers = original_handlers


async def test_connect_and_close(tmp_path: Path):
    log_path = tmp_path / "docketeer.log"
    with patch("docketeer_tui.client._redirect_logs_to_file", return_value=log_path):
        client = TUIClient()
        await client.connect()
        assert not client._closed
        await client.close()
        assert client._closed


async def test_subscribe_is_noop():
    client = TUIClient()
    await client.subscribe_to_my_messages()


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


async def test_list_dm_rooms():
    client = TUIClient()
    rooms = await client.list_dm_rooms()
    assert len(rooms) == 1
    assert rooms[0]["_id"] == ROOM_ID


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


async def test_unreact():
    client = TUIClient()
    await client.unreact("msg1", ":thumbsup:")


async def test_incoming_messages_yields_input():
    client = TUIClient()
    inputs = iter(["hello", None])
    with patch.object(client, "_read_input", side_effect=inputs):
        messages = []
        async for msg in client.incoming_messages():
            messages.append(msg)
        assert len(messages) == 1
        assert messages[0].text == "hello"
        assert messages[0].room_id == ROOM_ID
        assert messages[0].username == USERNAME
        assert messages[0].is_direct is True


async def test_incoming_messages_skips_blank():
    client = TUIClient()
    inputs = iter(["", "  ", "actual", None])
    with patch.object(client, "_read_input", side_effect=inputs):
        messages = []
        async for msg in client.incoming_messages():
            messages.append(msg)
        assert len(messages) == 1
        assert messages[0].text == "actual"


async def test_incoming_messages_stores_history():
    client = TUIClient()
    inputs = iter(["hello", None])
    with patch.object(client, "_read_input", side_effect=inputs):
        async for _ in client.incoming_messages():
            pass
    assert len(client._messages) == 1
    assert client._messages[0].username == USERNAME


async def test_incoming_messages_eof():
    client = TUIClient()
    with patch.object(client, "_read_input", side_effect=EOFError):
        messages = []
        async for msg in client.incoming_messages():
            messages.append(msg)
        assert len(messages) == 0


async def test_incoming_messages_keyboard_interrupt():
    client = TUIClient()
    with patch.object(client, "_read_input", side_effect=KeyboardInterrupt):
        messages = []
        async for msg in client.incoming_messages():
            messages.append(msg)
        assert len(messages) == 0


async def test_read_input_eof():
    client = TUIClient()
    with patch("builtins.input", side_effect=EOFError):
        assert client._read_input() is None


async def test_incoming_messages_closed():
    client = TUIClient()
    client._closed = True
    messages = []
    async for msg in client.incoming_messages():
        messages.append(msg)
    assert len(messages) == 0


async def test_set_status_debug_logging(caplog: pytest.LogCaptureFixture):
    client = TUIClient()
    with caplog.at_level(logging.DEBUG, logger="docketeer_tui.client"):
        await client.set_status("online", "ready")
    assert "status: online ready" in caplog.text


async def test_redirect_logs_to_file(tmp_path: Path):
    log_path = _redirect_logs_to_file(tmp_path)
    assert log_path == tmp_path / "docketeer.log"

    # use warning level since root logger default is WARNING
    test_logger = logging.getLogger("test.redirect")
    test_logger.warning("hello from test")

    # flush so the message is written
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "hello from test" in log_path.read_text()


def test_create_client():
    from docketeer_tui import create_client

    client = create_client()
    assert isinstance(client, TUIClient)
