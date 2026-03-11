"""Tests for the migration framework."""

import json
from pathlib import Path

import pytest

from docketeer.migrations import (
    _discover,
    _load_applied,
    _load_module,
    _save_applied,
    run_migrations,
)


def test_load_applied_empty(tmp_path: Path):
    assert _load_applied(tmp_path) == set()


def test_save_and_load_applied(tmp_path: Path):
    _save_applied(tmp_path, {1, 3})
    assert _load_applied(tmp_path) == {1, 3}


def test_save_applied_creates_parent(tmp_path: Path):
    nested = tmp_path / "deep" / "dir"
    _save_applied(nested, {1})
    assert _load_applied(nested) == {1}


def test_saved_state_is_sorted_json(tmp_path: Path):
    _save_applied(tmp_path, {3, 1, 2})
    raw = (tmp_path / "migrations").read_text()
    assert json.loads(raw) == [1, 2, 3]


def test_discover_finds_numbered_files():
    results = _discover()
    assert len(results) >= 1
    numbers = [n for n, _ in results]
    assert 1 in numbers


def test_discover_returns_sorted():
    results = _discover()
    numbers = [n for n, _ in results]
    assert numbers == sorted(numbers)


def test_load_module():
    results = _discover()
    _, path = results[0]
    module = _load_module(path)
    assert hasattr(module, "run")
    assert callable(module.run)


def test_run_migrations_applies_pending(tmp_path: Path):
    m1 = tmp_path / "001_first.py"
    m1.write_text("def run(data_dir, workspace):\n    (data_dir / 'ran_1').touch()\n")
    m2 = tmp_path / "002_second.py"
    m2.write_text("def run(data_dir, workspace):\n    (data_dir / 'ran_2').touch()\n")

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "docketeer.migrations._discover",
            lambda: [(1, m1), (2, m2)],
        )
        run_migrations(data_dir, tmp_path / "ws")

    assert (data_dir / "ran_1").exists()
    assert (data_dir / "ran_2").exists()
    assert _load_applied(data_dir) == {1, 2}


def test_run_migrations_skips_applied(tmp_path: Path):
    m1 = tmp_path / "001_first.py"
    m1.write_text("def run(data_dir, workspace):\n    (data_dir / 'ran_1').touch()\n")
    m2 = tmp_path / "002_second.py"
    m2.write_text("def run(data_dir, workspace):\n    (data_dir / 'ran_2').touch()\n")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _save_applied(data_dir, {1})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "docketeer.migrations._discover",
            lambda: [(1, m1), (2, m2)],
        )
        run_migrations(data_dir, tmp_path / "ws")

    assert not (data_dir / "ran_1").exists()
    assert (data_dir / "ran_2").exists()


def test_run_migrations_persists_after_each(tmp_path: Path):
    m1 = tmp_path / "001_ok.py"
    m1.write_text("def run(data_dir, workspace): pass\n")
    m2 = tmp_path / "002_boom.py"
    m2.write_text("def run(data_dir, workspace): raise RuntimeError('boom')\n")

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "docketeer.migrations._discover",
            lambda: [(1, m1), (2, m2)],
        )
        with pytest.raises(RuntimeError, match="boom"):
            run_migrations(data_dir, tmp_path / "ws")

    assert _load_applied(data_dir) == {1}


def test_run_migrations_no_pending(tmp_path: Path):
    m1 = tmp_path / "001_done.py"
    m1.write_text("def run(data_dir, workspace): pass\n")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _save_applied(data_dir, {1})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("docketeer.migrations._discover", lambda: [(1, m1)])
        run_migrations(data_dir, tmp_path / "ws")


def test_run_migrations_empty_discover(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("docketeer.migrations._discover", lambda: [])
        run_migrations(data_dir, tmp_path / "ws")

    assert not (data_dir / "migrations").exists()
