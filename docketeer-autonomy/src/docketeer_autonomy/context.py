"""Context provider for people profiles and line notes."""

import logging
from pathlib import Path

from docketeer.prompt import MessageParam

from .lines import load_line_context
from .people import load_person_context

log = logging.getLogger(__name__)


class AutonomyContextProvider:
    """Injects per-user profiles and per-line notes into conversation context."""

    def for_user(self, workspace: Path, username: str) -> list[MessageParam]:
        """Return context messages for a user's profile."""
        profile = load_person_context(workspace, username)
        if profile:
            log.info("→ BRAIN: [profile %s]: %.200s", username, profile)
            return [
                MessageParam(
                    role="system",
                    content=f"## What I know about @{username}\n\n{profile}",
                )
            ]
        return [
            MessageParam(
                role="system",
                content=(
                    f"I don't have a profile for @{username} yet. "
                    f"I can create people/{username}/profile.md to "
                    f"start one, or if I know this person under another "
                    f"name, I can create a symlink with the create_link tool."
                ),
            )
        ]

    def for_line(self, workspace: Path, slug: str) -> list[MessageParam]:
        """Return context messages for a line."""
        notes = load_line_context(workspace, slug)
        if notes:
            log.info("→ BRAIN: [line %s]: %.200s", slug, notes)
            return [
                MessageParam(
                    role="system",
                    content=f"## Line notes: {slug}\n\n{notes}",
                )
            ]
        return []


def create_context_provider() -> AutonomyContextProvider:
    """Entry point factory for the docketeer.context plugin group."""
    return AutonomyContextProvider()
