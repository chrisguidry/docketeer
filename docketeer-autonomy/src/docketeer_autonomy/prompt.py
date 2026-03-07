"""Autonomy prompt provider — SOUL.md, PRACTICE.md, BOOTSTRAP.md."""

from pathlib import Path

from docketeer.prompt import SystemBlock, ensure_template


def provide_autonomy_prompt(workspace: Path) -> list[SystemBlock]:
    """Build system prompt blocks from workspace template files.

    On first run (no SOUL.md yet), seeds all three templates including
    BOOTSTRAP.md. On subsequent runs, only SOUL.md and PRACTICE.md are
    ensured — BOOTSTRAP.md is a one-time file the agent deletes after setup.
    """
    soul_path = workspace / "SOUL.md"
    first_run = not soul_path.exists()

    ensure_template(workspace, "soul.md", package="docketeer_autonomy")
    ensure_template(workspace, "practice.md", package="docketeer_autonomy")
    if first_run:
        ensure_template(workspace, "bootstrap.md", package="docketeer_autonomy")

    stable_text = soul_path.read_text()

    practice_path = workspace / "PRACTICE.md"
    if practice_path.exists():
        stable_text += "\n\n" + practice_path.read_text()

    bootstrap_path = workspace / "BOOTSTRAP.md"
    if bootstrap_path.exists():
        stable_text += "\n\n" + bootstrap_path.read_text()

    return [SystemBlock(text=stable_text)]
