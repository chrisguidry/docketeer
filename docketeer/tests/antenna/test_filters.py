"""Tests for signal filter evaluation."""

from datetime import UTC, datetime

import pytest

from docketeer.antenna import Signal, SignalFilter, evaluate_filter, passes_filters


@pytest.fixture()
def signal() -> Signal:
    return Signal(
        band="test",
        signal_id="s1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        topic="events.push",
        payload={"action": "created", "repo": "docketeer", "count": "42"},
        summary="Push to docketeer",
    )


def test_eq_matches(signal: Signal):
    f = SignalFilter(path="payload.action", op="eq", value="created")
    assert evaluate_filter(f, signal) is True


def test_eq_no_match(signal: Signal):
    f = SignalFilter(path="payload.action", op="eq", value="deleted")
    assert evaluate_filter(f, signal) is False


def test_ne_matches(signal: Signal):
    f = SignalFilter(path="payload.action", op="ne", value="deleted")
    assert evaluate_filter(f, signal) is True


def test_ne_no_match(signal: Signal):
    f = SignalFilter(path="payload.action", op="ne", value="created")
    assert evaluate_filter(f, signal) is False


def test_contains_matches(signal: Signal):
    f = SignalFilter(path="payload.repo", op="contains", value="ocket")
    assert evaluate_filter(f, signal) is True


def test_contains_no_match(signal: Signal):
    f = SignalFilter(path="payload.repo", op="contains", value="xyz")
    assert evaluate_filter(f, signal) is False


def test_startswith_matches(signal: Signal):
    f = SignalFilter(path="topic", op="startswith", value="events.")
    assert evaluate_filter(f, signal) is True


def test_startswith_no_match(signal: Signal):
    f = SignalFilter(path="topic", op="startswith", value="other.")
    assert evaluate_filter(f, signal) is False


def test_exists_matches(signal: Signal):
    f = SignalFilter(path="payload.action", op="exists")
    assert evaluate_filter(f, signal) is True


def test_exists_missing(signal: Signal):
    f = SignalFilter(path="payload.missing", op="exists")
    assert evaluate_filter(f, signal) is False


def test_missing_path_returns_false(signal: Signal):
    f = SignalFilter(path="payload.nope", op="eq", value="x")
    assert evaluate_filter(f, signal) is False


def test_unknown_op_returns_false(signal: Signal):
    f = SignalFilter(path="topic", op="regex", value=".*")
    assert evaluate_filter(f, signal) is False


def test_passes_filters_all_match(signal: Signal):
    filters = [
        SignalFilter(path="payload.action", op="eq", value="created"),
        SignalFilter(path="topic", op="startswith", value="events."),
    ]
    assert passes_filters(filters, signal) is True


def test_passes_filters_one_fails(signal: Signal):
    filters = [
        SignalFilter(path="payload.action", op="eq", value="created"),
        SignalFilter(path="topic", op="eq", value="wrong"),
    ]
    assert passes_filters(filters, signal) is False


def test_passes_filters_empty():
    signal = Signal(
        band="test",
        signal_id="s1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        topic="t",
        payload={},
    )
    assert passes_filters([], signal) is True


def test_nested_payload_path(signal: Signal):
    nested = Signal(
        band="test",
        signal_id="s1",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        topic="t",
        payload={"commit": {"author": "chris"}},
    )
    f = SignalFilter(path="payload.commit.author", op="eq", value="chris")
    assert evaluate_filter(f, nested) is True


def test_top_level_field_path(signal: Signal):
    f = SignalFilter(path="band", op="eq", value="test")
    assert evaluate_filter(f, signal) is True


def test_missing_attribute_path(signal: Signal):
    f = SignalFilter(path="band.nonexistent", op="eq", value="x")
    assert evaluate_filter(f, signal) is False
