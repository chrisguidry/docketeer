"""Tests for docket task handlers and singleton management."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

from docketeer import tasks
from docketeer.brain import BrainResponse, MessageContent


@pytest.fixture(autouse=True)
def _reset_globals() -> Iterator[None]:
    """Clear global singletons between tests."""
    tasks._brain = None
    tasks._client = None
    yield
    tasks._brain = None
    tasks._client = None


def test_get_brain_raises_before_set():
    with pytest.raises(RuntimeError, match="Brain not initialized"):
        tasks.get_brain()


def test_get_client_raises_before_set():
    with pytest.raises(RuntimeError, match="ChatClient not initialized"):
        tasks.get_client()


def test_set_and_get_brain():
    brain = AsyncMock()
    tasks.set_brain(brain)
    assert tasks.get_brain() is brain


def test_set_and_get_client():
    client = AsyncMock()
    tasks.set_client(client)
    assert tasks.get_client() is client


def test_collection_contains_nudge():
    assert tasks.nudge in tasks.docketeer_tasks


@pytest.fixture()
def mock_brain() -> AsyncMock:
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="reminder sent")
    tasks.set_brain(brain)
    return brain


@pytest.fixture()
def mock_client() -> AsyncMock:
    client = AsyncMock()
    tasks.set_client(client)
    return client


async def test_nudge_with_room_sends_message(
    mock_brain: AsyncMock, mock_client: AsyncMock
):
    await tasks.nudge(prompt="hey there", room_id="room123")

    mock_brain.process.assert_called_once()
    call_args = mock_brain.process.call_args
    assert call_args[0][0] == "room123"
    content: MessageContent = call_args[0][1]
    assert content.username == "system"
    assert content.text == "hey there"

    mock_client.send_message.assert_called_once_with("room123", "reminder sent")


async def test_nudge_silent_uses_tasks_room(
    mock_brain: AsyncMock, mock_client: AsyncMock
):
    await tasks.nudge(prompt="do reflection", room_id="")

    mock_brain.process.assert_called_once()
    assert mock_brain.process.call_args[0][0] == "__tasks__"
    mock_client.send_message.assert_not_called()


async def test_nudge_no_send_on_empty_response(
    mock_brain: AsyncMock, mock_client: AsyncMock
):
    mock_brain.process.return_value = BrainResponse(text="")
    await tasks.nudge(prompt="silent work", room_id="room123")
    mock_client.send_message.assert_not_called()
