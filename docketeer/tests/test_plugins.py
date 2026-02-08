"""Tests for plugin discovery."""

from importlib.metadata import EntryPoint
from unittest.mock import MagicMock, patch

import pytest

from docketeer.plugins import discover_all, discover_one


def _make_ep(name: str, value: str = "some_module") -> EntryPoint:
    return EntryPoint(name=name, value=value, group="test.group")


def test_single_plugin_auto_selects():
    ep = _make_ep("only")
    with patch("docketeer.plugins.entry_points", return_value=[ep]):
        result = discover_one("test.group", "TEST")
    assert result is ep


def test_no_plugins_returns_none():
    with patch("docketeer.plugins.entry_points", return_value=[]):
        result = discover_one("test.group", "TEST")
    assert result is None


def test_multiple_plugins_with_env_var():
    ep_a = _make_ep("alpha")
    ep_b = _make_ep("beta")
    with (
        patch("docketeer.plugins.entry_points", return_value=[ep_a, ep_b]),
        patch.dict("os.environ", {"DOCKETEER_TEST": "beta"}),
    ):
        result = discover_one("test.group", "TEST")
    assert result is ep_b


def test_multiple_plugins_without_env_var():
    ep_a = _make_ep("alpha")
    ep_b = _make_ep("beta")
    with (
        patch("docketeer.plugins.entry_points", return_value=[ep_a, ep_b]),
        patch.dict("os.environ", {}, clear=True),
    ):
        with pytest.raises(RuntimeError, match="alpha.*beta"):
            discover_one("test.group", "TEST")


def test_multiple_plugins_bad_env_var_name():
    ep_a = _make_ep("alpha")
    ep_b = _make_ep("beta")
    with (
        patch("docketeer.plugins.entry_points", return_value=[ep_a, ep_b]),
        patch.dict("os.environ", {"DOCKETEER_TEST": "gamma"}),
    ):
        with pytest.raises(RuntimeError, match="alpha.*beta"):
            discover_one("test.group", "TEST")


# --- discover_all ---


def test_discover_all_loads_all_plugins():
    ep_a = MagicMock()
    ep_a.name = "alpha"
    ep_a.load.return_value = "module_a"
    ep_b = MagicMock()
    ep_b.name = "beta"
    ep_b.load.return_value = "module_b"
    with patch("docketeer.plugins.entry_points", return_value=[ep_a, ep_b]):
        result = discover_all("test.group")
    assert result == ["module_a", "module_b"]


def test_discover_all_no_plugins():
    with patch("docketeer.plugins.entry_points", return_value=[]):
        result = discover_all("test.group")
    assert result == []


def test_discover_all_skips_failures():
    good = MagicMock()
    good.name = "good"
    good.load.return_value = "module_good"
    bad = MagicMock()
    bad.name = "broken"
    bad.load.side_effect = ImportError("oops")
    with patch("docketeer.plugins.entry_points", return_value=[good, bad]):
        result = discover_all("test.group")
    assert result == ["module_good"]
