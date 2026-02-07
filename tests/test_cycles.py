"""Tests for the cycles module."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from docketeer.brain import Brain
from docketeer.cycles import (
    CONSOLIDATION_PROMPT,
    REVERIE_PROMPT,
    _build_cycle_prompt,
    _read_cycle_guidance,
    consolidation,
    reverie,
)
from docketeer.tasks import docketeer_tasks

from .conftest import FakeMessage, make_tool_use_block


def test_read_cycle_guidance_extracts_section(workspace: Path):
    (workspace / "CYCLES.md").write_text(
        "# Reverie\n\nCheck promises.\n\n# Consolidation\n\nReview journal.\n"
    )
    result = _read_cycle_guidance(workspace, "Reverie")
    assert result == "Check promises."


def test_read_cycle_guidance_last_section(workspace: Path):
    (workspace / "CYCLES.md").write_text(
        "# Reverie\n\nCheck promises.\n\n# Consolidation\n\nReview journal.\n"
    )
    result = _read_cycle_guidance(workspace, "Consolidation")
    assert result == "Review journal."


def test_read_cycle_guidance_missing_section(workspace: Path):
    (workspace / "CYCLES.md").write_text("# Reverie\n\nCheck promises.\n")
    result = _read_cycle_guidance(workspace, "Nonexistent")
    assert result == ""


def test_read_cycle_guidance_no_file(workspace: Path):
    result = _read_cycle_guidance(workspace, "Reverie")
    assert result == ""


def test_build_cycle_prompt_with_guidance(workspace: Path):
    (workspace / "CYCLES.md").write_text("# Reverie\n\nMy notes here.\n")
    result = _build_cycle_prompt(REVERIE_PROMPT, workspace, "Reverie")
    assert result.startswith(REVERIE_PROMPT)
    assert "Your own notes for this cycle:" in result
    assert "My notes here." in result


def test_build_cycle_prompt_without_guidance(workspace: Path):
    result = _build_cycle_prompt(REVERIE_PROMPT, workspace, "Reverie")
    assert result == REVERIE_PROMPT


async def test_reverie_calls_brain(brain: Brain, fake_messages: Any):
    with patch("docketeer.tasks.get_brain", return_value=brain):
        await reverie()
    assert "__tasks__" in brain._conversations
    msgs = brain._conversations["__tasks__"]
    assert any(REVERIE_PROMPT in str(m.get("content", "")) for m in msgs)


async def test_consolidation_calls_brain(brain: Brain, fake_messages: Any):
    with patch("docketeer.tasks.get_brain", return_value=brain):
        await consolidation()
    assert "__tasks__" in brain._conversations
    msgs = brain._conversations["__tasks__"]
    assert any(CONSOLIDATION_PROMPT in str(m.get("content", "")) for m in msgs)


async def test_reverie_empty_response(brain: Brain, fake_messages: Any):
    fake_messages.responses = [
        FakeMessage(content=[make_tool_use_block(name="list_files", input={})]),
        FakeMessage(content=[]),
    ]
    with patch("docketeer.tasks.get_brain", return_value=brain):
        await reverie()
    assert "__tasks__" in brain._conversations


async def test_consolidation_empty_response(brain: Brain, fake_messages: Any):
    fake_messages.responses = [
        FakeMessage(content=[make_tool_use_block(name="list_files", input={})]),
        FakeMessage(content=[]),
    ]
    with patch("docketeer.tasks.get_brain", return_value=brain):
        await consolidation()
    assert "__tasks__" in brain._conversations


def test_cycle_handlers_in_task_collection():
    assert reverie in docketeer_tasks
    assert consolidation in docketeer_tasks
