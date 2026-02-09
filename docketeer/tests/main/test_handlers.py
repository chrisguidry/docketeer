"""Tests for message handling, content building, response sending, and run modes."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from anthropic import AuthenticationError

from docketeer.brain import APOLOGY, Brain
from docketeer.chat import Attachment, IncomingMessage, RoomMessage
from docketeer.handlers import build_content, handle_message, send_response
from docketeer.main import run
from docketeer.prompt import BrainResponse
from docketeer.testing import MemoryChat

from ..conftest import (
    FakeMessage,
    FakeMessages,
    make_auth_error,
    make_text_block,
    make_tool_use_block,
)


async def test_handle_message_existing_room(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="old",
            )
        ],
    )
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
    chat._room_messages["new_room"] = [
        RoomMessage(
            message_id="m0",
            timestamp=datetime(2026, 2, 6, 15, 0, tzinfo=UTC),
            username="alice",
            display_name="Alice",
            text="old msg",
        )
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
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="x",
            )
        ],
    )
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
    assert content.message_id == "m1"
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


def test_run_start():
    with (
        patch("sys.argv", ["docketeer", "start"]),
        patch("docketeer.main.asyncio.run") as mock_run,
    ):
        run()
        mock_run.assert_called_once()
        coro = mock_run.call_args[0][0]
        coro.close()


async def test_handle_message_sends_typing_events(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="x",
            )
        ],
    )
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
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="x",
            )
        ],
    )
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


def test_run_start_dev():
    with (
        patch("sys.argv", ["docketeer", "start", "--dev"]),
        patch("docketeer.main.run_dev") as mock_dev,
    ):
        run()
        mock_dev.assert_called_once()


def test_run_snapshot():
    with (
        patch("sys.argv", ["docketeer", "snapshot"]),
        patch("docketeer.main.run_snapshot") as mock_snapshot,
    ):
        run()
        mock_snapshot.assert_called_once()


def test_run_no_command(capsys: pytest.CaptureFixture[str]):
    with patch("sys.argv", ["docketeer"]):
        run()
    assert "snapshot" in capsys.readouterr().out


# --- Error handling tests ---


def _make_incoming(room_id: str = "room1") -> IncomingMessage:
    return IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id=room_id,
        is_direct=True,
    )


async def test_handle_message_brain_error_sends_apology(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """When brain.process raises, handle_message sends an apology."""
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="x",
            )
        ],
    )
    with patch.object(brain, "process", side_effect=RuntimeError("boom")):
        await handle_message(chat, brain, _make_incoming())
    assert len(chat.sent_messages) == 1
    assert chat.sent_messages[0].text == APOLOGY


async def test_handle_message_auth_error_propagates(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """AuthenticationError propagates through handle_message."""
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="x",
            )
        ],
    )

    with patch.object(brain, "process", side_effect=make_auth_error()):
        with pytest.raises(AuthenticationError):
            await handle_message(chat, brain, _make_incoming())


async def test_handle_message_send_failure_does_not_crash(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """If send_message fails after a successful brain call, it doesn't crash."""
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="x",
            )
        ],
    )
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="reply")])]
    with patch.object(
        chat, "send_message", side_effect=ConnectionError("network down")
    ):
        await handle_message(chat, brain, _make_incoming())


async def test_handle_message_typing_cleared_on_error(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """Typing indicator is cleared even when brain.process raises."""
    brain.load_history(
        "room1",
        [
            RoomMessage(
                message_id="m0",
                timestamp=datetime(2026, 2, 6, 10, 0, tzinfo=UTC),
                username="a",
                display_name="A",
                text="x",
            )
        ],
    )
    with patch.object(brain, "process", side_effect=RuntimeError("boom")):
        await handle_message(chat, brain, _make_incoming())
    assert ("room1", False) in chat.typing_events
