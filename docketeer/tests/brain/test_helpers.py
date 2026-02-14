"""Tests for brain module-level helper functions."""

import importlib.resources
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from docketeer.audit import audit_log, log_usage
from docketeer.brain import Brain
from docketeer.prompt import (
    CacheControl,
    MessageContent,
    build_dynamic_context,
    build_system_blocks,
    ensure_template,
    extract_text,
)

from ..conftest import FakeMessage, FakeUsage, make_text_block


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


def test_build_system_blocks_stable_only(workspace: Path):
    (workspace / "SOUL.md").write_text("I am the soul")
    blocks = build_system_blocks(workspace)
    assert len(blocks) == 1
    assert "I am the soul" in blocks[0].text
    assert blocks[-1].cache_control == CacheControl()


def test_build_dynamic_context_basic(workspace: Path):
    ctx = build_dynamic_context("2026-02-06 10:00 EST", "chris", workspace)
    assert "Current time:" in ctx
    assert "@chris" in ctx


def test_build_dynamic_context_with_person_profile(workspace: Path):
    people = workspace / "people" / "chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("Chris likes coffee")
    ctx = build_dynamic_context("2026-02-06 10:00", "chris", workspace)
    assert "What I know about @chris" in ctx
    assert "Chris likes coffee" in ctx


def test_build_system_blocks_with_bootstrap(workspace: Path):
    (workspace / "SOUL.md").write_text("soul")
    (workspace / "BOOTSTRAP.md").write_text("bootstrap instructions")
    blocks = build_system_blocks(workspace)
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
    usage = FakeUsage()
    with caplog.at_level("INFO", logger="docketeer.audit"):
        log_usage("claude-opus-4-6", usage)  # type: ignore[arg-type]
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


async def test_summarize_webpage_with_purpose(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Summary!")])]
    result = await brain._summarize_webpage("page content", "find pricing info")
    assert result == "Summary!"
    assert (
        "for someone who wants to: find pricing info"
        in fake_messages.last_kwargs["messages"][0]["content"]
    )


async def test_summarize_webpage_without_purpose(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Summary!")])]
    result = await brain._summarize_webpage("page content", "")
    assert result == "Summary!"
    assert (
        "for someone who wants to"
        not in fake_messages.last_kwargs["messages"][0]["content"]
    )


async def test_summarize_webpage_non_text_block(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[MagicMock(spec=[])])]
    result = await brain._summarize_webpage("page content", "")
    assert isinstance(result, str)


async def test_classify_response_returns_true(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="true")])]
    result = await brain._classify_response(
        "https://example.com", 200, "content-type: text/html"
    )
    assert result is True


async def test_classify_response_returns_false(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="false")])]
    result = await brain._classify_response(
        "https://example.com/file.bin", 200, "content-type: application/octet-stream"
    )
    assert result is False


async def test_classify_response_non_text_block(brain: Brain, fake_messages: Any):
    fake_messages.responses = [FakeMessage(content=[MagicMock(spec=[])])]
    result = await brain._classify_response(
        "https://example.com", 200, "content-type: text/html"
    )
    assert result is False
