"""Tests for system prompt construction and extension point."""

from pathlib import Path
from unittest.mock import patch

from docketeer.prompt import (
    CacheControl,
    SystemBlock,
    _load_prompt_providers,
    build_system_blocks,
)


def test_build_system_blocks_includes_soul(workspace: Path):
    (workspace / "SOUL.md").write_text("I am the soul.")
    blocks = build_system_blocks(workspace, "2026-01-01T00:00:00", "chris")
    assert blocks[0].text == "I am the soul."
    assert blocks[0].cache_control == CacheControl()


def test_build_system_blocks_includes_bootstrap(workspace: Path):
    (workspace / "SOUL.md").write_text("Soul.")
    (workspace / "BOOTSTRAP.md").write_text("Bootstrap stuff.")
    blocks = build_system_blocks(workspace, "2026-01-01T00:00:00", "chris")
    assert "Bootstrap stuff." in blocks[0].text


def test_build_system_blocks_dynamic_parts(workspace: Path):
    (workspace / "SOUL.md").write_text("Soul.")
    blocks = build_system_blocks(workspace, "2026-01-01T00:00:00", "chris")
    dynamic = blocks[-1].text
    assert "Current time: 2026-01-01T00:00:00" in dynamic
    assert "Talking to: @chris" in dynamic


def test_build_system_blocks_calls_prompt_providers(workspace: Path):
    (workspace / "SOUL.md").write_text("Soul.")

    def fake_provider(ws: Path) -> list[SystemBlock]:
        return [SystemBlock(text=f"Skills from {ws.name}")]

    with patch("docketeer.prompt._prompt_providers", [fake_provider]):
        blocks = build_system_blocks(workspace, "2026-01-01T00:00:00", "chris")

    texts = [b.text for b in blocks]
    assert any("Skills from" in t for t in texts)


def test_build_system_blocks_provider_error_is_swallowed(workspace: Path):
    (workspace / "SOUL.md").write_text("Soul.")

    def bad_provider(ws: Path) -> list[SystemBlock]:
        raise RuntimeError("boom")

    with patch("docketeer.prompt._prompt_providers", [bad_provider]):
        blocks = build_system_blocks(workspace, "2026-01-01T00:00:00", "chris")

    assert len(blocks) >= 2


def test_build_system_blocks_provider_blocks_between_stable_and_dynamic(
    workspace: Path,
):
    (workspace / "SOUL.md").write_text("Soul.")

    def provider(ws: Path) -> list[SystemBlock]:
        return [SystemBlock(text="plugin-content")]

    with patch("docketeer.prompt._prompt_providers", [provider]):
        blocks = build_system_blocks(workspace, "2026-01-01T00:00:00", "chris")

    assert blocks[0].text == "Soul."
    assert blocks[1].text == "plugin-content"
    assert "Current time:" in blocks[-1].text


def test_system_block_to_api_dict():
    block = SystemBlock(text="hello")
    assert block.to_api_dict() == {"type": "text", "text": "hello"}


def test_system_block_to_api_dict_with_cache_control():
    block = SystemBlock(text="hello", cache_control=CacheControl())
    api_dict = block.to_api_dict()
    assert api_dict == {
        "type": "text",
        "text": "hello",
        "cache_control": {"type": "ephemeral", "ttl": "5m"},
    }


def test_load_prompt_providers_delegates_to_discover_all():
    fake_provider = lambda ws: []  # noqa: E731
    with patch("docketeer.prompt.discover_all", return_value=[fake_provider]) as mock:
        providers = _load_prompt_providers()
    mock.assert_called_once_with("docketeer.prompt")
    assert providers == [fake_provider]
