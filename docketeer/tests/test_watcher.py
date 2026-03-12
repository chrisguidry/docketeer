"""Tests for the workspace filesystem watcher."""

from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from watchfiles import Change

from docketeer.watcher import (
    WorkspaceWatcher,
    _format_workspace_pulse,
    _is_tuning_cursor,
    _workspace_filter,
)

type AwatchFunc = Callable[..., AsyncGenerator[set[tuple[Change, str]]]]


@pytest.fixture()
def watcher(tmp_path: Path) -> WorkspaceWatcher:
    return WorkspaceWatcher(tmp_path)


def test_drain_first_call_returns_empty(watcher: WorkspaceWatcher):
    assert watcher.drain("room1") == set()


def test_drain_returns_changes_since_last(watcher: WorkspaceWatcher):
    watcher.drain("room1")

    watcher._sequence += 1
    watcher._changes["notes/todo.md"] = watcher._sequence

    assert watcher.drain("room1") == {"notes/todo.md"}


def test_drain_multiple_rooms_independent(watcher: WorkspaceWatcher):
    watcher.drain("room1")
    watcher.drain("room2")

    watcher._sequence += 1
    watcher._changes["file_a.md"] = watcher._sequence

    watcher.drain("room1")

    watcher._sequence += 1
    watcher._changes["file_b.md"] = watcher._sequence

    # room2 hasn't drained since before both changes
    assert watcher.drain("room2") == {"file_a.md", "file_b.md"}


def test_drain_deduplicates_same_file(watcher: WorkspaceWatcher):
    watcher.drain("room1")

    watcher._sequence += 1
    watcher._changes["notes/todo.md"] = watcher._sequence
    watcher._sequence += 1
    watcher._changes["notes/todo.md"] = watcher._sequence

    result = watcher.drain("room1")
    assert result == {"notes/todo.md"}


def test_drain_returns_empty_when_no_new_changes(watcher: WorkspaceWatcher):
    watcher.drain("room1")

    watcher._sequence += 1
    watcher._changes["file.md"] = watcher._sequence

    watcher.drain("room1")
    assert watcher.drain("room1") == set()


@pytest.mark.parametrize(
    "path",
    [
        "/workspace/.git/objects/abc123",
        "/workspace/__pycache__/mod.cpython-312.pyc",
        "/workspace/.venv/lib/python3.12/site.py",
        "/workspace/node_modules/pkg/index.js",
        "/workspace/tmp/scratch.txt",
        "/workspace/sub/.git/HEAD",
        "/workspace/tunings/email/cursor",
        "/workspace/tunings/atproto/cursor",
    ],
)
def test_filter_skips_ignored_paths(path: str):
    assert _workspace_filter(Change.modified, path) is False


@pytest.mark.parametrize(
    "path",
    [
        "/workspace/notes/todo.md",
        "/workspace/journal/2026-03-03.md",
        "/workspace/people/chris/profile.md",
        "/workspace/SOUL.md",
        "/workspace/tunings/email.md",
        "/workspace/tunings/email/2026-03-11.jsonl",
    ],
)
def test_filter_allows_normal_files(path: str):
    assert _workspace_filter(Change.modified, path) is True


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("/", "workspace", "tunings", "email", "cursor"), True),
        (("/", "workspace", "tunings", "atproto", "cursor"), True),
        (("/", "workspace", "tunings", "email.md"), False),
        (("/", "workspace", "tunings"), False),
        (("/", "workspace", "notes", "cursor"), False),
    ],
)
def test_is_tuning_cursor(parts: tuple[str, ...], expected: bool):
    assert _is_tuning_cursor(parts) is expected


def test_format_pulse_few_files():
    result = _format_workspace_pulse({"a.md", "b.md"})
    assert result.startswith("[workspace updated by another context:")
    assert "a.md" in result
    assert "b.md" in result


def test_format_pulse_boundary_five():
    paths = {f"file{i}.md" for i in range(5)}
    result = _format_workspace_pulse(paths)
    for p in paths:
        assert p in result


def test_format_pulse_boundary_six():
    paths = {f"file{i}.md" for i in range(6)}
    result = _format_workspace_pulse(paths)
    assert "6 files changed" in result


def test_format_pulse_many_files():
    paths = {f"file{i}.md" for i in range(20)}
    result = _format_workspace_pulse(paths)
    assert "20 files changed" in result


def _make_fake_awatch(workspace: Path) -> AwatchFunc:
    async def _fake_awatch(
        *_args: object, **_kwargs: object
    ) -> AsyncGenerator[set[tuple[Change, str]]]:
        yield {
            (Change.added, str(workspace / "notes/new.md")),
            (Change.modified, str(workspace / "journal/today.md")),
        }

    return _fake_awatch


async def test_watch_records_changes(tmp_path: Path):
    watcher = WorkspaceWatcher(tmp_path)

    with patch("docketeer.watcher.awatch", _make_fake_awatch(tmp_path)):
        async with watcher:
            assert watcher._task is not None
            await watcher._task

    assert watcher._sequence == 2
    assert set(watcher._changes.keys()) == {
        "notes/new.md",
        "journal/today.md",
    }


async def test_watch_skips_paths_outside_workspace(tmp_path: Path):
    watcher = WorkspaceWatcher(tmp_path)

    async def _outside(
        *_args: object, **_kwargs: object
    ) -> AsyncGenerator[set[tuple[Change, str]]]:
        yield {(Change.modified, "/elsewhere/sneaky.txt")}

    with patch("docketeer.watcher.awatch", _outside):
        async with watcher:
            assert watcher._task is not None
            await watcher._task

    assert watcher._sequence == 0
    assert watcher._changes == {}


async def test_context_manager_stops_cleanly(tmp_path: Path):
    watcher = WorkspaceWatcher(tmp_path)
    with patch("docketeer.watcher.awatch", _make_fake_awatch(tmp_path)):
        async with watcher:
            assert watcher._task is not None
    assert watcher._task.done()


async def test_exit_without_enter(tmp_path: Path):
    watcher = WorkspaceWatcher(tmp_path)
    await watcher.__aexit__(None, None, None)
