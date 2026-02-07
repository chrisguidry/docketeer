"""Tests for message handling, content building, response sending, and run modes."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from docketeer.brain import Brain
from docketeer.chat import Attachment, IncomingMessage
from docketeer.main import build_content, handle_message, run, send_response
from docketeer.prompt import BrainResponse, HistoryMessage
from docketeer.testing import MemoryChat
from tests.conftest import (
    FakeMessage,
    FakeMessages,
    make_text_block,
    make_tool_use_block,
)


async def test_handle_message_existing_room(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    brain.load_history("room1", [HistoryMessage(role="user", username="a", text="old")])
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Got it!")])]

    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello nix",
        room_id="room1",
        is_direct=True,
    )
    await handle_message(chat, brain, msg)
    assert len(chat.sent_messages) == 1
    assert chat.sent_messages[0].text == "Got it!"


async def test_handle_message_new_room(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hello!")])]
    chat._room_history["new_room"] = [
        {
            "msg": "old msg",
            "u": {"_id": "u1", "username": "alice"},
            "ts": "2026-02-06T10:00:00Z",
        }
    ]

    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hi",
        room_id="new_room",
        is_direct=True,
    )
    await handle_message(chat, brain, msg)
    assert brain.has_history("new_room")
    assert len(chat.sent_messages) == 1
    info = brain._room_info["new_room"]
    assert info.is_direct is True
    assert info.members == ["alice"]


async def test_handle_message_text_only_no_status_change(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    brain.load_history("room1", [HistoryMessage(role="user", username="a", text="x")])
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="ok")])]

    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hi",
        room_id="room1",
        is_direct=True,
    )
    await handle_message(chat, brain, msg)
    assert chat.status_changes == []


async def test_build_content_text_only(chat: MemoryChat):
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id="r1",
        is_direct=True,
    )
    content = await build_content(chat, msg)
    assert content.text == "hello"
    assert content.username == "alice"
    assert content.images == []


async def test_build_content_with_attachments(chat: MemoryChat):
    chat._attachments["/img.png"] = b"imgdata"
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="look",
        room_id="r1",
        is_direct=True,
        attachments=[Attachment(url="/img.png", media_type="image/png")],
    )
    content = await build_content(chat, msg)
    assert len(content.images) == 1
    assert content.images[0] == ("image/png", b"imgdata")


async def test_build_content_attachment_failure(chat: MemoryChat):
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="look",
        room_id="r1",
        is_direct=True,
        attachments=[Attachment(url="/missing.png", media_type="image/png")],
    )
    content = await build_content(chat, msg)
    assert len(content.images) == 0


async def test_build_content_with_timestamp(chat: MemoryChat):
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hi",
        room_id="r1",
        is_direct=True,
        timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
    )
    content = await build_content(chat, msg)
    assert content.timestamp != ""


async def test_send_response(chat: MemoryChat):
    await send_response(chat, "room1", BrainResponse(text="reply"))
    assert chat.sent_messages[0].text == "reply"
    assert chat.sent_messages[0].room_id == "room1"


async def test_send_response_empty_skips_message(chat: MemoryChat):
    await send_response(chat, "room1", BrainResponse(text=""))
    assert chat.sent_messages == []


def test_run_normal_mode():
    with (
        patch("docketeer.main.argparse.ArgumentParser.parse_args") as mock_args,
        patch("docketeer.main.asyncio.run") as mock_run,
    ):
        mock_args.return_value = MagicMock(dev=False)
        run()
        mock_run.assert_called_once()
        coro = mock_run.call_args[0][0]
        coro.close()


async def test_handle_message_sends_typing_events(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    brain.load_history("room1", [HistoryMessage(role="user", username="a", text="x")])
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="reply")])]

    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hi",
        room_id="room1",
        is_direct=True,
    )
    await handle_message(chat, brain, msg)
    # Should have typing=True (on first text) then typing=False (after process)
    assert ("room1", True) in chat.typing_events
    assert ("room1", False) in chat.typing_events


async def test_handle_message_tool_use_status_changes(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    brain.load_history("room1", [HistoryMessage(role="user", username="a", text="x")])
    fake_messages.responses = [
        FakeMessage(
            content=[make_tool_use_block(name="list_files", input={"path": ""})],
        ),
        FakeMessage(content=[make_text_block(text="Done!")]),
    ]

    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="list files",
        room_id="room1",
        is_direct=True,
    )
    await handle_message(chat, brain, msg)
    statuses = [s[0] for s in chat.status_changes]
    # on_tool_start sets away, on_tool_end sets online — only around tool execution
    assert statuses == ["away", "online"]


def test_run_dev_mode():
    with (
        patch("docketeer.main.argparse.ArgumentParser.parse_args") as mock_args,
        patch("docketeer.main.run_dev") as mock_dev,
    ):
        mock_args.return_value = MagicMock(dev=True)
        run()
        mock_dev.assert_called_once()
