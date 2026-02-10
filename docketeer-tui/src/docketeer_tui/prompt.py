"""Prompt provider for the TUI chat backend."""

import os
from pathlib import Path

from docketeer.prompt import SystemBlock


def provide_tui_context(workspace: Path) -> list[SystemBlock]:
    """Add terminal-specific context to the system prompt.

    Only injects context when the TUI is the active chat backend,
    so other backends aren't affected by having docketeer-tui installed.
    """
    if os.environ.get("DOCKETEER_CHAT") != "tui":
        return []
    return [
        SystemBlock(
            text=(
                "## Chat environment\n\n"
                "You are running in a local terminal session. There is one user "
                "typing messages directly. Keep responses concise and well-formatted "
                "for a terminal — use markdown, but avoid very wide tables or images."
            ),
        ),
    ]
