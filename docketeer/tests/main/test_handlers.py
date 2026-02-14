"""Tests for message handling, content building, response sending, and run modes."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from anthropic import AuthenticationError

from docketeer.brain import APOLOGY, Brain
from docketeer.chat import Attachment, IncomingMessage, RoomKind, RoomMessage
from docketeer.handlers import build_content, handle_message, send_response
from docketeer.main import run
from docketeer.prompt import BrainResponse
from docketeer.testing import MemoryChat, Reaction

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
        kind=RoomKind.direct,
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
        kind=RoomKind.direct,
    )
    await handle_message(chat, brain, msg)
    assert brain.has_history("new_room")
    assert len(chat.sent_messages) == 1


async def test_handle_message_eyes_reaction(
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
        kind=RoomKind.direct,
    )
    await handle_message(chat, brain, msg)
    assert chat.reactions[0] == Reaction("m1", ":brain:", "react")
    assert chat.reactions[1] == Reaction("m1", ":brain:", "unreact")


async def test_build_content_text_only(chat: MemoryChat):
    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="hello",
        room_id="r1",
        kind=RoomKind.direct,
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
        kind=RoomKind.direct,
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
        kind=RoomKind.direct,
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
        kind=RoomKind.direct,
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
        kind=RoomKind.direct,
    )
    await handle_message(chat, brain, msg)
    # Should have typing=True (on first text) then typing=False (after process)
    assert ("room1", True) in chat.typing_events
    assert ("room1", False) in chat.typing_events


async def test_handle_message_tool_use_stops_typing(
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
        kind=RoomKind.direct,
    )
    await handle_message(chat, brain, msg)
    # on_tool_start stops typing, no status changes
    assert ("room1", False) in chat.typing_events
    assert chat.status_changes == []


async def test_handle_message_tool_emoji_reactions(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """Tool use reacts with the tool's emoji and unreacts in finally."""
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
        kind=RoomKind.direct,
    )
    await handle_message(chat, brain, msg)
    # Should have :brain: react, :open_file_folder: react, then unreacts for both
    reacted = [r for r in chat.reactions if r.action == "react"]
    unreacted = [r for r in chat.reactions if r.action == "unreact"]
    assert Reaction("m1", ":brain:", "react") in reacted
    assert Reaction("m1", ":open_file_folder:", "react") in reacted
    assert Reaction("m1", ":brain:", "unreact") in unreacted
    assert Reaction("m1", ":open_file_folder:", "unreact") in unreacted


async def test_handle_message_tool_emoji_no_duplicates(
    chat: MemoryChat, brain: Brain, fake_messages: FakeMessages
):
    """Multiple tools with the same emoji only react once."""
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
            content=[
                make_tool_use_block(id="t1", name="list_files", input={"path": ""}),
                make_tool_use_block(id="t2", name="read_file", input={"path": "x"}),
            ],
        ),
        FakeMessage(content=[make_text_block(text="Done!")]),
    ]

    msg = IncomingMessage(
        message_id="m1",
        user_id="u1",
        username="alice",
        display_name="Alice",
        text="list and read",
        room_id="room1",
        kind=RoomKind.direct,
    )
    await handle_message(chat, brain, msg)
    folder_reacts = [
        r
        for r in chat.reactions
        if r.emoji == ":open_file_folder:" and r.action == "react"
    ]
    assert len(folder_reacts) == 1


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
        kind=RoomKind.direct,
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
