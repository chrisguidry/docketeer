"""Flatten signal logs from tunings/<name>/signals/ to tunings/<name>/.

Signal JSONL files were incorrectly written to a nested signals/
subdirectory.  Move them up to the tuning data directory, merging
by timestamp when a date file already exists at both levels.
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def _merge_jsonl(source: Path, dest: Path) -> None:
    """Merge two JSONL files, sorting all records by timestamp."""
    lines = dest.read_text().splitlines() + source.read_text().splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    records.sort(key=lambda r: r.get("timestamp", ""))
    dest.write_text("".join(json.dumps(r) + "\n" for r in records))


def run(data_dir: Path, workspace: Path) -> None:
    """Move signal logs out of signals/ subdirectories."""
    tunings_dir = workspace / "tunings"
    if not tunings_dir.is_dir():
        return

    for tuning_dir in sorted(tunings_dir.iterdir()):
        signals_dir = tuning_dir / "signals"
        if not signals_dir.is_dir():
            continue

        for jsonl in sorted(signals_dir.glob("*.jsonl")):
            dest = tuning_dir / jsonl.name
            if dest.exists():
                _merge_jsonl(jsonl, dest)
                jsonl.unlink()
                log.info("Merged %s into %s", jsonl, dest)
            else:
                jsonl.rename(dest)
                log.info("Moved %s to %s", jsonl, dest)

        if not any(signals_dir.iterdir()):
            signals_dir.rmdir()
            log.info("Removed empty %s", signals_dir)
