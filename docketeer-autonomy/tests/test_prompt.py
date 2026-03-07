"""Tests for the autonomy prompt provider."""

from pathlib import Path
from unittest.mock import patch

from docketeer.prompt import SystemBlock
from docketeer_autonomy.prompt import provide_autonomy_prompt


def test_provide_autonomy_prompt_seeds_templates(workspace: Path):
    blocks = provide_autonomy_prompt(workspace)
    assert len(blocks) == 1
    assert (workspace / "SOUL.md").exists()
    assert (workspace / "PRACTICE.md").exists()
    assert (workspace / "BOOTSTRAP.md").exists()
    assert "personality" in blocks[0].text.lower() or len(blocks[0].text) > 0


def test_provide_autonomy_prompt_first_run_includes_bootstrap(workspace: Path):
    blocks = provide_autonomy_prompt(workspace)
    assert "First run" in blocks[0].text


def test_provide_autonomy_prompt_existing_soul_no_bootstrap(workspace: Path):
    (workspace / "SOUL.md").write_text("Custom soul.")
    blocks = provide_autonomy_prompt(workspace)
    assert blocks[0].text.startswith("Custom soul.")
    assert not (workspace / "BOOTSTRAP.md").exists()


def test_provide_autonomy_prompt_includes_practice(workspace: Path):
    (workspace / "SOUL.md").write_text("Soul.")
    (workspace / "PRACTICE.md").write_text("Practice notes.")
    blocks = provide_autonomy_prompt(workspace)
    assert "Practice notes." in blocks[0].text


def test_provide_autonomy_prompt_includes_bootstrap_if_present(workspace: Path):
    (workspace / "SOUL.md").write_text("Soul.")
    (workspace / "BOOTSTRAP.md").write_text("Bootstrap!")
    blocks = provide_autonomy_prompt(workspace)
    assert "Bootstrap!" in blocks[0].text


def test_provide_autonomy_prompt_returns_system_blocks(workspace: Path):
    blocks = provide_autonomy_prompt(workspace)
    assert all(isinstance(b, SystemBlock) for b in blocks)


def test_provide_autonomy_prompt_soul_only(workspace: Path):
    """When PRACTICE.md doesn't exist, prompt contains only SOUL.md."""
    (workspace / "SOUL.md").write_text("Soul only.")
    with patch("docketeer_autonomy.prompt.ensure_template"):
        blocks = provide_autonomy_prompt(workspace)
    assert blocks[0].text == "Soul only."
