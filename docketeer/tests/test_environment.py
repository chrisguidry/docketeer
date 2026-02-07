"""Tests for environment variable helpers."""

from datetime import timedelta
from pathlib import Path

import pytest

from docketeer.environment import (
    _parse_iso8601_duration,
    get_int,
    get_path,
    get_str,
    get_timedelta,
)


def test_get_str_with_default():
    assert get_str("NONEXISTENT_TEST_VAR_XYZ", "fallback") == "fallback"


def test_get_str_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCKETEER_TEST_STR", "hello")
    assert get_str("TEST_STR") == "hello"


def test_get_str_raises_without_default():
    with pytest.raises(KeyError):
        get_str("NONEXISTENT_TEST_VAR_XYZ")


def test_get_int_default():
    assert get_int("NONEXISTENT_TEST_VAR_XYZ", 42) == 42


def test_get_int_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCKETEER_TEST_INT", "99")
    assert get_int("TEST_INT", 0) == 99


def test_get_path_default(tmp_path: Path):
    result = get_path("NONEXISTENT_TEST_VAR_XYZ", str(tmp_path / "default"))
    assert result == tmp_path / "default"


def test_get_path_expands_tilde():
    result = get_path("NONEXISTENT_TEST_VAR_XYZ", "~/.test")
    assert "~" not in str(result)


def test_get_path_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DOCKETEER_TEST_PATH", str(tmp_path / "custom"))
    assert get_path("TEST_PATH", "/unused") == tmp_path / "custom"


def test_get_timedelta_default():
    default = timedelta(minutes=30)
    assert get_timedelta("NONEXISTENT_TEST_VAR_XYZ", default) == default


def test_get_timedelta_integer_seconds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCKETEER_TEST_TD", "1800")
    assert get_timedelta("TEST_TD", timedelta()) == timedelta(seconds=1800)


def test_get_timedelta_iso8601(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCKETEER_TEST_TD", "PT30M")
    assert get_timedelta("TEST_TD", timedelta()) == timedelta(minutes=30)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PT1H", timedelta(hours=1)),
        ("PT30M", timedelta(minutes=30)),
        ("PT45S", timedelta(seconds=45)),
        ("PT1H30M", timedelta(hours=1, minutes=30)),
        ("PT1H30M45S", timedelta(hours=1, minutes=30, seconds=45)),
        ("P1D", timedelta(days=1)),
        ("P1DT2H", timedelta(days=1, hours=2)),
        ("P2DT3H15M10S", timedelta(days=2, hours=3, minutes=15, seconds=10)),
    ],
)
def test_parse_iso8601_duration(value: str, expected: timedelta):
    assert _parse_iso8601_duration(value) == expected


def test_parse_iso8601_duration_invalid():
    with pytest.raises(ValueError, match="Cannot parse"):
        _parse_iso8601_duration("not-a-duration")


def test_data_dir_workspace_audit_derivation():
    from docketeer import environment

    assert environment.WORKSPACE_PATH == environment.DATA_DIR / "memory"
    assert environment.AUDIT_PATH == environment.DATA_DIR / "audit"
