"""Workspace filesystem watcher for detecting external changes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from watchfiles import Change, awatch

log = logging.getLogger(__name__)

_IGNORED_DIRS = {".git", "__pycache__", ".venv", "node_modules", "tmp"}


@runtime_checkable
class Watcher(Protocol):
    """Protocol for workspace change detection."""

    async def __aenter__(self) -> Watcher: ...
    async def __aexit__(self, *exc: object) -> None: ...
    def drain(self, room_id: str) -> set[str]: ...


def _workspace_filter(_change: Change, path: str) -> bool:
    """Skip noisy directories that don't represent meaningful workspace changes."""
    parts = Path(path).parts
    return not any(part in _IGNORED_DIRS for part in parts)


def _format_workspace_pulse(changed: set[str]) -> str:
    """Format a system message listing changed workspace files."""
    if len(changed) <= 5:
        paths = ", ".join(sorted(changed))
        return f"[workspace updated by another context: {paths}]"
    return f"[workspace updated by another context: {len(changed)} files changed]"


class WorkspaceWatcher:
    """Watches the workspace for filesystem changes and provides per-room drains."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace
        self._sequence = 0
        self._changes: dict[str, int] = {}
        self._room_seqs: dict[str, int] = {}
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> WorkspaceWatcher:
        self._task = asyncio.create_task(self._watch())
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _watch(self) -> None:
        async for batch in awatch(
            self._workspace,
            stop_event=self._stop,
            watch_filter=_workspace_filter,
        ):
            for _change_type, abs_path in batch:
                try:
                    relative = str(Path(abs_path).relative_to(self._workspace))
                except ValueError:
                    continue
                self._sequence += 1
                self._changes[relative] = self._sequence

    def drain(self, room_id: str) -> set[str]:
        """Return paths changed since this room's last drain.

        First call for a room returns empty (catches up to current sequence).
        """
        last_seq = self._room_seqs.get(room_id)
        self._room_seqs[room_id] = self._sequence

        if last_seq is None:
            return set()

        return {path for path, seq in self._changes.items() if seq > last_seq}
