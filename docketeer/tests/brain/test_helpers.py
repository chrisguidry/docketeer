"""Tests for brain module-level helper functions."""

import importlib.resources
import json
from pathlib import Path
from typing import Any

import pytest

from docketeer.audit import audit_log, log_usage
from docketeer.brain import Brain
from docketeer.prompt import (
    CacheControl,
    MessageContent,
    RoomInfo,
    build_system_blocks,
    ensure_template,
    extract_text,
)

from ..conftest import FakeMessage, make_text_block


def test_ensure_template_copies_when_missing(workspace: Path):
    ensure_template(workspace, "soul.md")
    target = workspace / "SOUL.md"
    assert target.exists()
    source = importlib.resources.files("docketeer").joinpath("soul.md")
    assert target.read_text() == source.read_text()


def test_ensure_template_skips_existing(workspace: Path):
    target = workspace / "SOUL.md"
    target.write_text("custom soul")
    ensure_template(workspace, "soul.md")
    assert target.read_text() == "custom soul"


def test_build_system_blocks_without_person_context(workspace: Path):
    (workspace / "SOUL.md").write_text("I am the soul")
    blocks = build_system_blocks(workspace, "2026-02-06 10:00 EST", "chris")
    assert len(blocks) == 2
    assert "I am the soul" in blocks[0].text
    assert blocks[0].cache_control == CacheControl()
    assert "Current time:" in blocks[1].text
    assert "@chris" in blocks[1].text


def test_build_system_blocks_with_person_context(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    blocks = build_system_blocks(
        workspace, "2026-02-06 10:00", "chris", person_context="Chris likes coffee"
    )
    dynamic = blocks[1].text
    assert "What I know about @chris" in dynamic
    assert "Chris likes coffee" in dynamic


def test_build_system_blocks_dm_room(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    info = RoomInfo(room_id="r1", is_direct=True, members=["nix", "alice"])
    blocks = build_system_blocks(workspace, "2026-02-06 10:00", "alice", room_info=info)
    dynamic = blocks[1].text
    assert "Room: DM with @nix" in dynamic


def test_build_system_blocks_dm_room_no_others(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    info = RoomInfo(room_id="r1", is_direct=True, members=["alice"])
    blocks = build_system_blocks(workspace, "2026-02-06 10:00", "alice", room_info=info)
    dynamic = blocks[1].text
    assert "Room: DM" in dynamic


def test_build_system_blocks_group_room_with_name(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    info = RoomInfo(
        room_id="r1", is_direct=False, members=["alice", "bob", "chris"], name="general"
    )
    blocks = build_system_blocks(workspace, "2026-02-06 10:00", "chris", room_info=info)
    dynamic = blocks[1].text
    assert "Room: #general (with @alice, @bob)" in dynamic


def test_build_system_blocks_group_room_no_name(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    info = RoomInfo(room_id="r1", is_direct=False, members=["alice", "bob"])
    blocks = build_system_blocks(workspace, "2026-02-06 10:00", "bob", room_info=info)
    dynamic = blocks[1].text
    assert "Room: group chat (with @alice)" in dynamic


def test_build_system_blocks_group_room_no_others(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    info = RoomInfo(room_id="r1", is_direct=False, members=["chris"], name="solo")
    blocks = build_system_blocks(workspace, "2026-02-06 10:00", "chris", room_info=info)
    dynamic = blocks[1].text
    assert "Room: #solo" in dynamic
    assert "(with" not in dynamic


def test_build_system_blocks_with_bootstrap(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    (workspace / "BOOTSTRAP.md").write_text("bootstrap instructions")
    blocks = build_system_blocks(workspace, "2026-02-06 10:00", "chris")
    assert "bootstrap instructions" in blocks[0].text


def testaudit_log_creates_dir_and_appends(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    audit_log(audit_dir, "read_file", {"path": "test.txt"}, "content", False)
    files = list(audit_dir.glob("*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text().strip())
    assert record["tool"] == "read_file"
    assert record["is_error"] is False


def testaudit_log_appends_to_existing(tmp_path: Path):
    audit_dir = tmp_path / "audit"
    audit_log(audit_dir, "tool_a", {}, "ok", False)
    audit_log(audit_dir, "tool_b", {}, "ok", False)
    files = list(audit_dir.glob("*.jsonl"))
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 2


def testlog_usage(caplog: pytest.LogCaptureFixture):
    msg = FakeMessage()
    with caplog.at_level("INFO", logger="docketeer.audit"):
        log_usage(msg)  # type: ignore[arg-type]
    assert "Tokens:" in caplog.text


def test_extract_text_string():
    assert extract_text("hello") == "hello"


def test_extract_text_blocks():
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
        {"type": "image", "source": {}},
    ]
    assert extract_text(blocks) == "first\nsecond"


def test_extract_text_tool_result():
    blocks = [{"type": "tool_result", "content": "some result data here"}]
    result = extract_text(blocks)
    assert "tool result:" in result


def test_extract_text_hasattr_block():
    block = make_text_block(text="from block")
    assert extract_text([block]) == "from block"


def test_extract_text_mixed_block_types():
    """Exercise all block-type branches with multiple iterations."""
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "tool_result", "content": "result data"},
        make_text_block(text="from sdk"),
        {"type": "image"},
    ]
    result = extract_text(blocks)
    assert "first" in result
    assert "tool result:" in result
    assert "from sdk" in result


def test_extract_text_tool_result_empty_content():
    """Tool result with empty content exercises the False branch."""
    blocks = [
        {"type": "tool_result", "content": ""},
        {"type": "text", "text": "after"},
    ]
    result = extract_text(blocks)
    assert "tool result:" not in result
    assert "after" in result


def test_extract_text_non_dict_without_text():
    """Non-dict block without .text exercises the hasattr False branch."""
    blocks = [42, {"type": "text", "text": "ok"}]
    result = extract_text(blocks)
    assert result == "ok"


def test_extract_text_skips_other():
    blocks = [{"type": "image"}, {"type": "unknown"}]
    assert extract_text(blocks) == ""


async def test_process_synthetic_room_clears_tool_room_id(
    brain: Brain, fake_messages: Any
):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="ok")])]
    await brain.process("__tasks__", MessageContent(username="system", text="reverie"))
    assert brain.tool_context.room_id == ""
