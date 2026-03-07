"""Context provider for people profiles and room notes."""

import logging
from pathlib import Path

from docketeer.prompt import MessageParam

from .people import load_person_context
from .rooms import load_room_context

log = logging.getLogger(__name__)


class AutonomyContextProvider:
    """Injects per-user profiles and per-room notes into conversation context."""

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

    def for_room(self, workspace: Path, room_slug: str) -> list[MessageParam]:
        """Return context messages for a room."""
        room_notes = load_room_context(workspace, room_slug)
        if room_notes:
            log.info("→ BRAIN: [room %s]: %.200s", room_slug, room_notes)
            return [
                MessageParam(
                    role="system",
                    content=f"## Room notes: {room_slug}\n\n{room_notes}",
                )
            ]
        return []


def create_context_provider() -> AutonomyContextProvider:
    """Entry point factory for the docketeer.context plugin group."""
    return AutonomyContextProvider()
