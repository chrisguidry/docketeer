"""Tests for antenna data types, persistence, and band discovery."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from docketeer.antenna import (
    Signal,
    SignalFilter,
    Tuning,
    discover_bands,
    load_tunings,
    save_tunings,
)
from docketeer.testing import MemoryBand


def test_signal_frozen():
    s = Signal(
        band="test",
        signal_id="s1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        topic="events.push",
        payload={"action": "created"},
    )
    assert s.band == "test"
    assert s.summary == ""


def test_signal_filter_frozen():
    f = SignalFilter(path="topic", op="eq", value="events.push")
    assert f.path == "topic"


def test_tuning_target_line_defaults_to_name():
    t = Tuning(name="my-tuning", band="wicket", topic="events")
    assert t.target_line == "my-tuning"


def test_tuning_target_line_uses_explicit():
    t = Tuning(name="my-tuning", band="wicket", topic="events", line="custom-line")
    assert t.target_line == "custom-line"


def test_save_and_load_tunings(tmp_path: Path):
    tunings = [
        Tuning(
            name="github-prs",
            band="wicket",
            topic="github/pulls",
            filters=[SignalFilter(path="payload.action", op="eq", value="opened")],
            line="opensource",
            batch_window=10.0,
            max_batch=5,
        ),
        Tuning(name="bluesky", band="atproto", topic="posts"),
    ]
    save_tunings(tmp_path, tunings)

    loaded = load_tunings(tmp_path)
    assert len(loaded) == 2

    t = loaded[0]
    assert t.name == "github-prs"
    assert t.band == "wicket"
    assert t.topic == "github/pulls"
    assert len(t.filters) == 1
    assert t.filters[0].path == "payload.action"
    assert t.filters[0].op == "eq"
    assert t.filters[0].value == "opened"
    assert t.line == "opensource"
    assert t.batch_window == 10.0
    assert t.max_batch == 5

    t2 = loaded[1]
    assert t2.name == "bluesky"
    assert t2.line == ""
    assert t2.target_line == "bluesky"


def test_load_tunings_no_file(tmp_path: Path):
    assert load_tunings(tmp_path) == []


def test_save_tunings_creates_dir(tmp_path: Path):
    data_dir = tmp_path / "nested" / "data"
    save_tunings(data_dir, [Tuning(name="t", band="b", topic="x")])
    assert (data_dir / "tunings.json").exists()


def test_tuning_json_format(tmp_path: Path):
    save_tunings(tmp_path, [Tuning(name="t", band="b", topic="x")])
    data = json.loads((tmp_path / "tunings.json").read_text())
    assert isinstance(data, list)
    assert data[0]["name"] == "t"


def test_discover_bands_empty():
    with patch("docketeer.antenna.discover_all", return_value=[]):
        bands = discover_bands()
    assert bands == {}


def test_discover_bands_loads_factories():
    def factory() -> MemoryBand:
        return MemoryBand("test-band")

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        bands = discover_bands()
    assert "test-band" in bands
    assert bands["test-band"].name == "test-band"
