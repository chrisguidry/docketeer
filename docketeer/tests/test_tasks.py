"""Tests for docket task handlers (parse_every, nudge, one-shot auto-delete)."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from docketeer.brain import APOLOGY
from docketeer.brain.backend import BackendAuthError
from docketeer.prompt import BrainResponse, MessageContent
from docketeer.tasks import docketeer_tasks, nudge, nudge_every, parse_every

from .conftest import make_api_connection_error, make_backend_auth_error


def test_collection_contains_nudge():
    assert nudge in docketeer_tasks


def test_collection_contains_nudge_every():
    assert nudge_every in docketeer_tasks


# --- parse_every tests ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PT30M", timedelta(minutes=30)),
        ("PT2H", timedelta(hours=2)),
        ("P1D", timedelta(days=1)),
        ("PT30S", timedelta(seconds=30)),
        ("PT1H30M", timedelta(hours=1, minutes=30)),
        ("P1DT12H", timedelta(days=1, hours=12)),
        ("P2DT3H15M45S", timedelta(days=2, hours=3, minutes=15, seconds=45)),
        ("pt30m", timedelta(minutes=30)),
    ],
)
def test_parse_every_durations(value: str, expected: timedelta):
    assert parse_every(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "0 9 * * *",
        "@daily",
        "",
        "not-a-duration",
        "30m",
    ],
)
def test_parse_every_non_durations_return_none(value: str):
    assert parse_every(value) is None


# --- nudge tests with real prompt files ---


async def test_nudge_with_room_sends_message(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="reminder sent")
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["hey_there"],
        room_id="room123",
        brain=brain,
        client=client,
        task_key="hey-there",
    )

    brain.process.assert_called_once()
    call_args = brain.process.call_args
    assert call_args[0][0] == "__task__:hey-there"
    content: MessageContent = call_args[0][1]
    assert content.username is None
    assert content.text == "hey there"
    assert call_args[1]["chat_room"] == "room123"

    client.send_message.assert_called_once_with(
        "room123", "reminder sent", thread_id=""
    )


async def test_nudge_silent_uses_tasks_room(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="done")
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["do_reflection"],
        room_id="",
        brain=brain,
        client=client,
        task_key="do-reflection",
    )

    brain.process.assert_called_once()
    assert brain.process.call_args[0][0] == "__task__:do-reflection"
    client.send_message.assert_not_called()


async def test_nudge_with_explicit_line(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="done")
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["hey_there"],
        line="research",
        room_id="room123",
        brain=brain,
        client=client,
        task_key="hey-there",
    )

    brain.process.assert_called_once()
    assert brain.process.call_args[0][0] == "research"


async def test_nudge_injects_line_context(workspace: Path, task_files: dict):
    lines_dir = workspace / "lines"
    lines_dir.mkdir()
    (lines_dir / "research.md").write_text("Focus on academic papers and citations.")

    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="done")
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["hey_there"],
        line="research",
        brain=brain,
        client=client,
        task_key="hey-there",
    )

    kwargs = brain.process.call_args[1]
    assert len(kwargs["system_context"]) == 1
    assert "academic papers" in kwargs["system_context"][0].text


async def test_nudge_no_line_context_when_no_file(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="done")
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["hey_there"],
        brain=brain,
        client=client,
        task_key="hey-there",
    )

    kwargs = brain.process.call_args[1]
    assert kwargs["system_context"] == []


async def test_nudge_no_send_on_empty_response(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="")
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["silent_work"],
        room_id="room123",
        brain=brain,
        client=client,
    )
    client.send_message.assert_not_called()


# --- Error handling tests ---


async def test_nudge_brain_error_sends_apology_to_room(
    workspace: Path, task_files: dict
):
    """When brain.process raises, nudge sends an apology if room_id is set."""
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["do_stuff"],
        room_id="room123",
        brain=brain,
        client=client,
    )
    client.send_message.assert_called_once_with("room123", APOLOGY, thread_id="")


async def test_nudge_silent_error_logged_only(workspace: Path, task_files: dict):
    """When brain.process raises and there's no room_id, no message is sent."""
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["do_stuff"], room_id="", brain=brain, client=client
    )
    client.send_message.assert_not_called()


async def test_nudge_auth_error_propagates(workspace: Path, task_files: dict):
    """BackendAuthError propagates from nudge."""
    brain = AsyncMock()
    brain.process.side_effect = make_backend_auth_error()
    client = AsyncMock()

    with pytest.raises(BackendAuthError):
        await nudge(
            prompt_file=task_files["do_stuff"],
            room_id="room123",
            brain=brain,
            client=client,
        )


# --- Thread support ---


async def test_nudge_with_thread_sends_to_thread(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="thread reply")
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["reply_here"],
        room_id="room123",
        thread_id="parent_1",
        brain=brain,
        client=client,
    )

    content: MessageContent = brain.process.call_args[0][1]
    assert content.thread_id == "parent_1"

    client.send_message.assert_called_once_with(
        "room123", "thread reply", thread_id="parent_1"
    )


async def test_nudge_without_thread_sends_to_channel(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="channel reply")
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["reply_here"],
        room_id="room123",
        brain=brain,
        client=client,
    )

    content: MessageContent = brain.process.call_args[0][1]
    assert content.thread_id == ""

    client.send_message.assert_called_once_with(
        "room123", "channel reply", thread_id=""
    )


async def test_nudge_thread_error_sends_apology_to_thread(
    workspace: Path, task_files: dict
):
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["do_stuff"],
        room_id="room123",
        thread_id="parent_1",
        brain=brain,
        client=client,
    )
    client.send_message.assert_called_once_with(
        "room123", APOLOGY, thread_id="parent_1"
    )


# --- one-shot auto-delete tests ---


async def test_nudge_deletes_task_file_after_firing(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="done")
    client = AsyncMock()

    task_path = workspace / task_files["hey_there"]
    assert task_path.exists()

    await nudge(
        prompt_file=task_files["hey_there"],
        brain=brain,
        client=client,
        task_key="hey-there",
    )

    assert not task_path.exists()


async def test_nudge_tolerates_file_deleted_during_processing(
    workspace: Path, task_files: dict
):
    task_path = workspace / task_files["hey_there"]

    async def delete_during_process(*args: object, **kwargs: object) -> BrainResponse:
        task_path.unlink()
        return BrainResponse(text="done")

    brain = AsyncMock()
    brain.process.side_effect = delete_during_process
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["hey_there"],
        brain=brain,
        client=client,
        task_key="hey-there",
    )

    assert not task_path.exists()


async def test_nudge_error_preserves_task_file(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.side_effect = make_api_connection_error()
    client = AsyncMock()

    task_path = workspace / task_files["do_stuff"]

    await nudge(
        prompt_file=task_files["do_stuff"],
        brain=brain,
        client=client,
        task_key="do-stuff",
    )

    assert task_path.exists()
