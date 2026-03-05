"""Tests for model tier threading through cycles, tasks, and handlers."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from docketeer.brain.core import CHAT_MODEL, CONSOLIDATION_MODEL, REVERIE_MODEL
from docketeer.cycles import consolidation, reverie
from docketeer.prompt import BrainResponse
from docketeer.tasks import nudge, nudge_every


async def test_reverie_uses_reverie_tier(workspace: Path):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="thoughts")
    await reverie(brain=brain, workspace=workspace)
    assert brain.process.call_args[1]["tier"] == REVERIE_MODEL


async def test_consolidation_uses_consolidation_tier(workspace: Path):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="reflection")
    await consolidation(brain=brain, workspace=workspace)
    assert brain.process.call_args[1]["tier"] == CONSOLIDATION_MODEL


async def test_nudge_uses_chat_tier_by_default(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="nudged")
    client = AsyncMock()
    await nudge(
        prompt_file=task_files["hey_there"], room_id="room1", brain=brain, client=client
    )
    assert brain.process.call_args[1]["tier"] == CHAT_MODEL


async def test_nudge_passes_explicit_tier(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="nudged")
    client = AsyncMock()
    await nudge(
        prompt_file=task_files["hey_there"],
        room_id="room1",
        tier="smart",
        brain=brain,
        client=client,
    )
    assert brain.process.call_args[1]["tier"] == "smart"


async def test_nudge_every_uses_chat_tier_by_default(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()
    await nudge_every(
        prompt_file=task_files["check"],
        every="PT30M",
        room_id="room1",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )
    assert brain.process.call_args[1]["tier"] == CHAT_MODEL


async def test_nudge_every_passes_explicit_tier(workspace: Path, task_files: dict):
    brain = AsyncMock()
    brain.process.return_value = BrainResponse(text="ok")
    client = AsyncMock()
    perpetual = MagicMock()
    await nudge_every(
        prompt_file=task_files["check"],
        every="PT30M",
        room_id="room1",
        tier="balanced",
        brain=brain,
        client=client,
        perpetual=perpetual,
    )
    assert brain.process.call_args[1]["tier"] == "balanced"
