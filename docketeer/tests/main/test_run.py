"""Tests for run modes and TUI detection."""

from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer.main import _will_use_tui, run


def test_will_use_tui_true():
    ep = type("EP", (), {"name": "tui"})()
    with patch("docketeer.main.discover_one", return_value=ep):
        assert _will_use_tui() is True


def test_will_use_tui_false():
    ep = type("EP", (), {"name": "rocketchat"})()
    with patch("docketeer.main.discover_one", return_value=ep):
        assert _will_use_tui() is False


def test_will_use_tui_none():
    with patch("docketeer.main.discover_one", return_value=None):
        assert _will_use_tui() is False


def test_will_use_tui_multiple_backends():
    with patch("docketeer.main.discover_one", side_effect=RuntimeError("ambiguous")):
        assert _will_use_tui() is False


def test_run_start(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCKETEER_CHAT", "rocketchat")
    with (
        patch("sys.argv", ["docketeer", "start"]),
        patch("docketeer.main.asyncio.run") as mock_run,
    ):
        run()
        mock_run.assert_called_once()
        coro = mock_run.call_args[0][0]
        coro.close()


def test_run_start_tui_logs_to_file(tmp_path: Path):
    tui_ep = type("EP", (), {"name": "tui"})()
    with (
        patch("sys.argv", ["docketeer", "start"]),
        patch("docketeer.main.discover_one", return_value=tui_ep),
        patch("docketeer.main.environment.DATA_DIR", tmp_path),
        patch("docketeer.main.asyncio.run") as mock_run,
    ):
        run()
        mock_run.assert_called_once()
        coro = mock_run.call_args[0][0]
        coro.close()
    assert (tmp_path / "docketeer.log").exists()


def test_run_start_dev():
    with (
        patch("sys.argv", ["docketeer", "start", "--dev"]),
        patch("docketeer.main.run_dev") as mock_dev,
    ):
        run()
        mock_dev.assert_called_once()


def test_run_snapshot():
    with (
        patch("sys.argv", ["docketeer", "snapshot"]),
        patch("docketeer.main.run_snapshot") as mock_snapshot,
    ):
        run()
        mock_snapshot.assert_called_once()


def test_run_no_command(capsys: pytest.CaptureFixture[str]):
    with patch("sys.argv", ["docketeer"]):
        run()
    assert "snapshot" in capsys.readouterr().out
