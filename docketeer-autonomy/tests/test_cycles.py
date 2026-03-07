"""Tests for the cycles module."""

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from docket.dependencies import Cron, Perpetual

from docketeer import environment
from docketeer.brain import Brain
from docketeer.brain.backend import BackendAuthError
from docketeer.chat import RoomInfo, RoomKind, RoomMessage
from docketeer.prompt import extract_text
from docketeer.testing import MemoryChat
from docketeer_autonomy.cycles import (
    CONSOLIDATION_CRON,
    CONSOLIDATION_MODEL,
    CONSOLIDATION_PROMPT,
    REVERIE_INTERVAL,
    REVERIE_MODEL,
    REVERIE_PROMPT,
    _build_cycle_prompt,
    _read_cycle_guidance,
    consolidation,
    reverie,
)
from docketeer_autonomy.tasks import _autonomy_tasks

from .conftest import (
    FakeMessage,
    make_backend_auth_error,
    make_tool_use_block,
)


def test_read_cycle_guidance_extracts_section(workspace: Path):
    (workspace / "PRACTICE.md").write_text(
        "# Reverie\n\nCheck promises.\n\n# Consolidation\n\nReview journal.\n"
    )
    result = _read_cycle_guidance(workspace, "Reverie")
    assert result == "Check promises."


def test_read_cycle_guidance_last_section(workspace: Path):
    (workspace / "PRACTICE.md").write_text(
        "# Reverie\n\nCheck promises.\n\n# Consolidation\n\nReview journal.\n"
    )
    result = _read_cycle_guidance(workspace, "Consolidation")
    assert result == "Review journal."


def test_read_cycle_guidance_missing_section(workspace: Path):
    (workspace / "PRACTICE.md").write_text("# Reverie\n\nCheck promises.\n")
    result = _read_cycle_guidance(workspace, "Nonexistent")
    assert result == ""


def test_read_cycle_guidance_no_file(workspace: Path):
    result = _read_cycle_guidance(workspace, "Reverie")
    assert result == ""


def test_build_cycle_prompt_with_guidance(workspace: Path):
    (workspace / "PRACTICE.md").write_text("# Reverie\n\nMy notes here.\n")
    result = _build_cycle_prompt(REVERIE_PROMPT, workspace, "Reverie")
    assert result.startswith(REVERIE_PROMPT)
    assert "Your own notes for this cycle:" in result
    assert "My notes here." in result


def test_build_cycle_prompt_without_guidance(workspace: Path):
    result = _build_cycle_prompt(REVERIE_PROMPT, workspace, "Reverie")
    assert result == REVERIE_PROMPT


async def test_reverie_calls_brain(brain: Brain, workspace: Path, fake_messages: Any):
    await reverie(task_key="reverie", brain=brain, workspace=workspace)
    assert "__task__:reverie" in brain._conversations
    msgs = brain._conversations["__task__:reverie"]
    assert any(REVERIE_PROMPT in extract_text(m.content) for m in msgs)


async def test_consolidation_calls_brain(
    brain: Brain, workspace: Path, fake_messages: Any
):
    await consolidation(task_key="consolidation", brain=brain, workspace=workspace)
    assert "__task__:consolidation" in brain._conversations
    msgs = brain._conversations["__task__:consolidation"]
    assert any(CONSOLIDATION_PROMPT in extract_text(m.content) for m in msgs)


async def test_reverie_empty_response(
    brain: Brain, workspace: Path, fake_messages: Any
):
    fake_messages.responses = [
        FakeMessage(content=[make_tool_use_block(name="list_files", input={})]),
        FakeMessage(content=[]),
    ]
    await reverie(task_key="reverie", brain=brain, workspace=workspace)
    assert "__task__:reverie" in brain._conversations


async def test_consolidation_empty_response(
    brain: Brain, workspace: Path, fake_messages: Any
):
    fake_messages.responses = [
        FakeMessage(content=[make_tool_use_block(name="list_files", input={})]),
        FakeMessage(content=[]),
    ]
    await consolidation(task_key="consolidation", brain=brain, workspace=workspace)
    assert "__task__:consolidation" in brain._conversations


def test_cycle_handlers_in_task_collection():
    assert reverie in _autonomy_tasks
    assert consolidation in _autonomy_tasks


# --- Error handling tests ---


async def test_reverie_error_returns_early(workspace: Path):
    brain = AsyncMock()
    brain.process.side_effect = RuntimeError("boom")
    await reverie(task_key="reverie", brain=brain, workspace=workspace)
    brain.process.assert_called_once()


async def test_consolidation_error_returns_early(workspace: Path):
    brain = AsyncMock()
    brain.process.side_effect = RuntimeError("boom")
    await consolidation(task_key="consolidation", brain=brain, workspace=workspace)
    brain.process.assert_called_once()


async def test_reverie_auth_error_propagates(workspace: Path):
    brain = AsyncMock()
    brain.process.side_effect = make_backend_auth_error()
    with pytest.raises(BackendAuthError):
        await reverie(task_key="reverie", brain=brain, workspace=workspace)


async def test_consolidation_auth_error_propagates(workspace: Path):
    brain = AsyncMock()
    brain.process.side_effect = make_backend_auth_error()
    with pytest.raises(BackendAuthError):
        await consolidation(task_key="consolidation", brain=brain, workspace=workspace)


# --- Digest integration tests ---

EST = timezone(timedelta(hours=-5))


async def test_reverie_includes_digest(
    brain: Brain, workspace: Path, fake_messages: Any
):
    chat = MemoryChat()
    room = RoomInfo(room_id="general", kind=RoomKind.public, members=[], name="general")
    chat._rooms = [room]
    now = datetime.now().astimezone()
    chat._room_messages["general"] = [
        RoomMessage(
            message_id="m1",
            timestamp=now - timedelta(minutes=5),
            username="alice",
            display_name="Alice",
            text="Hey everyone!",
        ),
    ]
    await reverie(
        task_key="reverie",
        brain=brain,
        workspace=workspace,
        chat=chat,
        backend=None,
    )
    msgs = brain._conversations["__task__:reverie"]
    all_content = " ".join(extract_text(m.content) for m in msgs)
    assert "#general" in all_content
    assert "Hey everyone!" in all_content
    assert REVERIE_PROMPT in all_content


async def test_reverie_without_backend(
    brain: Brain, workspace: Path, fake_messages: Any
):
    chat = MemoryChat()
    await reverie(
        task_key="reverie",
        brain=brain,
        workspace=workspace,
        chat=chat,
        backend=None,
    )
    assert "__task__:reverie" in brain._conversations


# --- Configuration tests ---


def test_reverie_default_uses_module_interval():
    from docketeer_autonomy import cycles

    defaults = cycles.reverie.__defaults__
    assert defaults is not None
    assert isinstance(defaults[0], Perpetual)
    assert defaults[0].every == REVERIE_INTERVAL


def test_consolidation_default_uses_module_cron():
    from docketeer_autonomy import cycles

    defaults = cycles.consolidation.__defaults__
    assert defaults is not None
    assert isinstance(defaults[0], Cron)
    assert defaults[0].expression == CONSOLIDATION_CRON


def test_consolidation_cron_uses_local_timezone():
    from docketeer_autonomy import cycles

    defaults = cycles.consolidation.__defaults__
    assert defaults is not None
    cron = defaults[0]
    assert isinstance(cron, Cron)
    assert cron.tz == environment.local_timezone()


def test_reverie_interval_is_timedelta():
    assert isinstance(REVERIE_INTERVAL, timedelta)


def test_consolidation_cron_is_string():
    assert isinstance(CONSOLIDATION_CRON, str)


def test_reverie_model_is_string():
    assert isinstance(REVERIE_MODEL, str)


def test_consolidation_model_is_string():
    assert isinstance(CONSOLIDATION_MODEL, str)


# --- _read_cycle_guidance regex parsing ---


def test_read_cycle_guidance_basic(tmp_path: Path):
    (tmp_path / "PRACTICE.md").write_text(
        "# Reverie\nScan for patterns.\n\n# Consolidation\nReflect on the day.\n"
    )
    assert _read_cycle_guidance(tmp_path, "Reverie") == "Scan for patterns."
    assert _read_cycle_guidance(tmp_path, "Consolidation") == "Reflect on the day."


def test_read_cycle_guidance_section_at_end(tmp_path: Path):
    (tmp_path / "PRACTICE.md").write_text("# Reverie\nEnd of file content.\n")
    assert _read_cycle_guidance(tmp_path, "Reverie") == "End of file content."


def test_read_cycle_guidance_ignores_subheadings(tmp_path: Path):
    (tmp_path / "PRACTICE.md").write_text(
        "# Reverie\nIntro.\n## Details\nMore info.\n\n# Consolidation\nDone.\n"
    )
    result = _read_cycle_guidance(tmp_path, "Reverie")
    assert "## Details" in result
    assert "More info." in result


def test_read_cycle_guidance_missing_section_specific(tmp_path: Path):
    (tmp_path / "PRACTICE.md").write_text("# Other\nStuff.\n")
    assert _read_cycle_guidance(tmp_path, "Reverie") == ""


def test_read_cycle_guidance_missing_file_specific(tmp_path: Path):
    assert _read_cycle_guidance(tmp_path, "Reverie") == ""


# --- consecutive failure tracking ---


@pytest.fixture(autouse=True)
def _reset_failure_counters() -> Iterator[None]:
    from docketeer_autonomy import cycles

    cycles._consecutive_failures.clear()
    yield
    cycles._consecutive_failures.clear()


async def test_reverie_consecutive_failures_escalate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    from docketeer_autonomy import cycles

    brain = AsyncMock()
    brain.process.side_effect = RuntimeError("boom")

    for i in range(4):
        with caplog.at_level(logging.DEBUG):
            caplog.clear()
            await cycles.reverie(brain=brain, workspace=tmp_path)
            if i < 2:
                assert any(r.levelno == logging.WARNING for r in caplog.records)
            else:
                assert any(r.levelno == logging.ERROR for r in caplog.records)

    assert cycles._consecutive_failures["reverie"] == 4


async def test_reverie_success_resets_counter(tmp_path: Path):
    from docketeer_autonomy import cycles

    brain = AsyncMock()
    brain.process.side_effect = RuntimeError("boom")
    await cycles.reverie(brain=brain, workspace=tmp_path)
    assert cycles._consecutive_failures.get("reverie") == 1

    brain.process.side_effect = None
    brain.process.return_value = AsyncMock(text="ok")
    await cycles.reverie(brain=brain, workspace=tmp_path)
    assert "reverie" not in cycles._consecutive_failures


# --- Model tier tests ---


async def test_reverie_uses_reverie_tier(workspace: Path):
    brain = AsyncMock()
    brain.process.return_value = AsyncMock(text="thoughts")
    await reverie(brain=brain, workspace=workspace)
    assert brain.process.call_args[1]["tier"] == REVERIE_MODEL


async def test_consolidation_uses_consolidation_tier(workspace: Path):
    brain = AsyncMock()
    brain.process.return_value = AsyncMock(text="reflection")
    await consolidation(brain=brain, workspace=workspace)
    assert brain.process.call_args[1]["tier"] == CONSOLIDATION_MODEL
