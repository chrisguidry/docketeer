"""Tests for antenna data types and band discovery."""

from datetime import UTC, datetime
from unittest.mock import patch

from docketeer.antenna import (
    Signal,
    SignalFilter,
    Tuning,
    _parse_tuning,
    discover_bands,
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


def test_tuning_retention_days_defaults_to_7():
    t = Tuning(name="t", band="b", topic="x")
    assert t.retention_days == 7


def test_parse_tuning_reads_retention_days():
    meta = {"band": "imap", "topic": "INBOX", "retention_days": 30}
    t = _parse_tuning("mail", meta)
    assert t.retention_days == 30


def test_parse_tuning_defaults_retention_days():
    meta = {"band": "imap", "topic": "INBOX"}
    t = _parse_tuning("mail", meta)
    assert t.retention_days == 7
