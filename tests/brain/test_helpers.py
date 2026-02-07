"""Tests for brain module-level helper functions."""

import importlib.resources
import json
from pathlib import Path

import pytest

from docketeer.brain import (
    _audit_log,
    _build_system_blocks,
    _ensure_template,
    _extract_text,
    _log_usage,
)

from ..conftest import FakeMessage, make_text_block


def test_ensure_template_copies_when_missing(workspace: Path):
    _ensure_template(workspace, "soul.md")
    target = workspace / "SOUL.md"
    assert target.exists()
    source = importlib.resources.files("docketeer").joinpath("soul.md")
    assert target.read_text() == source.read_text()


def test_ensure_template_skips_existing(workspace: Path):
    target = workspace / "SOUL.md"
    target.write_text("custom soul")
    _ensure_template(workspace, "soul.md")
    assert target.read_text() == "custom soul"


def test_build_system_blocks_without_person_context(workspace: Path):
    (workspace / "SOUL.md").write_text("I am the soul")
    blocks = _build_system_blocks(workspace, "2026-02-06 10:00 EST", "chris")
    assert len(blocks) == 2
    assert "I am the soul" in blocks[0]["text"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "Current time:" in blocks[1]["text"]
    assert "@chris" in blocks[1]["text"]


def test_build_system_blocks_with_person_context(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    blocks = _build_system_blocks(
        workspace, "2026-02-06 10:00", "chris", person_context="Chris likes coffee"
    )
    dynamic = blocks[1]["text"]
    assert "What I know about @chris" in dynamic
    assert "Chris likes coffee" in dynamic


def test_build_system_blocks_with_bootstrap(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    (workspace / "BOOTSTRAP.md").write_text("bootstrap instructions")
    blocks = _build_system_blocks(workspace, "2026-02-06 10:00", "chris")
    assert "bootstrap instructions" in blocks[0]["text"]


def test_audit_log_creates_dir_and_appends(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    _audit_log(audit_dir, "read_file", {"path": "test.txt"}, "content", False)
    files = list(audit_dir.glob("*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text().strip())
    assert record["tool"] == "read_file"
    assert record["is_error"] is False


def test_audit_log_appends_to_existing(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    _audit_log(audit_dir, "tool_a", {}, "ok", False)
    _audit_log(audit_dir, "tool_b", {}, "ok", False)
    files = list(audit_dir.glob("*.jsonl"))
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 2


def test_log_usage(caplog: pytest.LogCaptureFixture):
    msg = FakeMessage()
    with caplog.at_level("INFO", logger="docketeer.brain"):
        _log_usage(msg)  # type: ignore[arg-type]
    assert "Tokens:" in caplog.text


def test_extract_text_string():
    assert _extract_text("hello") == "hello"


def test_extract_text_blocks():
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
        {"type": "image", "source": {}},
    ]
    assert _extract_text(blocks) == "first\nsecond"


def test_extract_text_tool_result():
    blocks = [{"type": "tool_result", "content": "some result data here"}]
    result = _extract_text(blocks)
    assert "tool result:" in result


def test_extract_text_hasattr_block():
    block = make_text_block(text="from block")
    assert _extract_text([block]) == "from block"


def test_extract_text_mixed_block_types():
    """Exercise all block-type branches with multiple iterations."""
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "tool_result", "content": "result data"},
        make_text_block(text="from sdk"),
        {"type": "image"},
    ]
    result = _extract_text(blocks)
    assert "first" in result
    assert "tool result:" in result
    assert "from sdk" in result


def test_extract_text_tool_result_empty_content():
    """Tool result with empty content exercises the False branch."""
    blocks = [
        {"type": "tool_result", "content": ""},
        {"type": "text", "text": "after"},
    ]
    result = _extract_text(blocks)
    assert "tool result:" not in result
    assert "after" in result


def test_extract_text_non_dict_without_text():
    """Non-dict block without .text exercises the hasattr False branch."""
    blocks = [42, {"type": "text", "text": "ok"}]
    result = _extract_text(blocks)
    assert result == "ok"


def test_extract_text_skips_other():
    blocks = [{"type": "image"}, {"type": "unknown"}]
    assert _extract_text(blocks) == ""
