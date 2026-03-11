"""Tests for migration 002: flatten signal logs."""

import json
from pathlib import Path

from docketeer.migrations import _discover, _load_module

_m002_path = next(p for n, p in _discover() if n == 2)
_m002 = _load_module(_m002_path)
run = _m002.run
_merge_jsonl = _m002._merge_jsonl


def _record(signal_id: str, timestamp: str) -> str:
    return json.dumps({"signal_id": signal_id, "timestamp": timestamp})


def test_moves_jsonl_up(tmp_path: Path):
    workspace = tmp_path / "workspace"
    signals = workspace / "tunings" / "github" / "signals"
    signals.mkdir(parents=True)
    (signals / "2026-03-10.jsonl").write_text(
        _record("s1", "2026-03-10T12:00:00") + "\n"
    )

    run(tmp_path, workspace)

    assert (workspace / "tunings" / "github" / "2026-03-10.jsonl").exists()
    assert not signals.exists()


def test_merges_collisions_temporally(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tuning = workspace / "tunings" / "github"
    tuning.mkdir(parents=True)

    (tuning / "2026-03-10.jsonl").write_text(
        _record("s1", "2026-03-10T08:00:00")
        + "\n"
        + _record("s3", "2026-03-10T16:00:00")
        + "\n"
    )

    signals = tuning / "signals"
    signals.mkdir()
    (signals / "2026-03-10.jsonl").write_text(
        _record("s2", "2026-03-10T12:00:00") + "\n"
    )

    run(tmp_path, workspace)

    merged = (tuning / "2026-03-10.jsonl").read_text().strip().splitlines()
    assert len(merged) == 3
    ids = [json.loads(line)["signal_id"] for line in merged]
    assert ids == ["s1", "s2", "s3"]
    assert not signals.exists()


def test_no_tunings_dir(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run(tmp_path, workspace)


def test_no_signals_subdir(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tuning = workspace / "tunings" / "github"
    tuning.mkdir(parents=True)
    (tuning / "2026-03-10.jsonl").write_text(
        _record("s1", "2026-03-10T12:00:00") + "\n"
    )

    run(tmp_path, workspace)

    assert (tuning / "2026-03-10.jsonl").exists()


def test_multiple_tunings(tmp_path: Path):
    workspace = tmp_path / "workspace"
    for name in ("alpha", "beta"):
        signals = workspace / "tunings" / name / "signals"
        signals.mkdir(parents=True)
        (signals / "2026-03-11.jsonl").write_text(
            _record(name, "2026-03-11T00:00:00") + "\n"
        )

    run(tmp_path, workspace)

    for name in ("alpha", "beta"):
        assert (workspace / "tunings" / name / "2026-03-11.jsonl").exists()
        assert not (workspace / "tunings" / name / "signals").exists()


def test_signals_dir_kept_if_non_jsonl_remains(tmp_path: Path):
    workspace = tmp_path / "workspace"
    signals = workspace / "tunings" / "github" / "signals"
    signals.mkdir(parents=True)
    (signals / "2026-03-10.jsonl").write_text(
        _record("s1", "2026-03-10T12:00:00") + "\n"
    )
    (signals / "notes.txt").write_text("keep me")

    run(tmp_path, workspace)

    assert (workspace / "tunings" / "github" / "2026-03-10.jsonl").exists()
    assert signals.exists()
    assert (signals / "notes.txt").exists()


def test_merge_jsonl_sorts_by_timestamp(tmp_path: Path):
    source = tmp_path / "source.jsonl"
    dest = tmp_path / "dest.jsonl"
    dest.write_text(_record("late", "2026-03-10T23:00:00") + "\n")
    source.write_text(_record("early", "2026-03-10T01:00:00") + "\n")

    _merge_jsonl(source, dest)

    lines = dest.read_text().strip().splitlines()
    ids = [json.loads(line)["signal_id"] for line in lines]
    assert ids == ["early", "late"]


def test_skips_tuning_md_files(tmp_path: Path):
    workspace = tmp_path / "workspace"
    tunings = workspace / "tunings"
    tunings.mkdir(parents=True)
    (tunings / "github.md").write_text("---\nband: wicket\n---\n")

    run(tmp_path, workspace)

    assert (tunings / "github.md").read_text() == "---\nband: wicket\n---\n"
