"""Tests for the TUI prompt provider."""

from pathlib import Path

import pytest

from docketeer_tui.prompt import provide_tui_context


def test_provide_tui_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DOCKETEER_CHAT", "tui")
    blocks = provide_tui_context(tmp_path)
    assert len(blocks) == 1
    assert "terminal session" in blocks[0].text
    assert blocks[0].cache_control is None


def test_provide_tui_context_inactive(tmp_path: Path):
    blocks = provide_tui_context(tmp_path)
    assert blocks == []
