"""Security and edge case tests for nudge tasks."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from docketeer.tasks import nudge, nudge_every

# --- path traversal security tests ---


async def test_nudge_rejects_path_outside_workspace(
    workspace: Path, task_files: dict[str, str]
) -> None:
    """Verify that path traversal attacks are blocked."""
    brain = AsyncMock()
    client = AsyncMock()

    with pytest.raises(ValueError, match="outside workspace"):
        await nudge(prompt_file="../etc/passwd", room_id="", brain=brain, client=client)


async def test_nudge_every_rejects_path_outside_workspace(
    workspace: Path, task_files: dict[str, str]
) -> None:
    """Verify that path traversal attacks are blocked for recurring tasks."""
    brain = AsyncMock()
    client = AsyncMock()
    perpetual = MagicMock()

    with pytest.raises(ValueError, match="outside workspace"):
        await nudge_every(
            prompt_file="../etc/passwd",
            every="PT30M",
            room_id="",
            brain=brain,
            client=client,
            perpetual=perpetual,
        )


# --- empty prompt tests ---


async def test_nudge_empty_prompt_file_exits_early(
    workspace: Path, task_files: dict[str, str]
) -> None:
    """Empty prompt file should exit early without calling brain."""
    brain = AsyncMock()
    client = AsyncMock()

    await nudge(
        prompt_file=task_files["empty"], room_id="room123", brain=brain, client=client
    )

    brain.process.assert_not_called()
    client.send_message.assert_not_called()


async def test_nudge_every_empty_prompt_file_exits_early(
    workspace: Path, task_files: dict[str, str]
) -> None:
    """Empty prompt file should exit early without calling brain - no reschedule."""
    brain = AsyncMock()
    client = AsyncMock()
    perpetual = MagicMock()

    await nudge_every(
        prompt_file=task_files["empty"],
        every="PT30M",
        room_id="room123",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )

    brain.process.assert_not_called()
    # Should NOT reschedule - nothing to do
    perpetual.after.assert_not_called()
