"""Tests for system prompt construction and extension point."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer.prompt import (
    CacheControl,
    MessageParam,
    SystemBlock,
    _load_prompt_providers,
    build_dynamic_context,
    build_system_blocks,
    format_message_time,
)


def test_build_system_blocks_includes_soul(workspace: Path):
    (workspace / "SOUL.md").write_text("I am the soul.")
    blocks = build_system_blocks(workspace)
    assert blocks[0].text == "I am the soul."
    assert blocks[-1].cache_control == CacheControl()


def test_build_system_blocks_includes_bootstrap(workspace: Path):
    (workspace / "SOUL.md").write_text("Soul.")
    (workspace / "BOOTSTRAP.md").write_text("Bootstrap stuff.")
    blocks = build_system_blocks(workspace)
    assert "Bootstrap stuff." in blocks[0].text


def test_build_dynamic_context_includes_time_and_username(workspace: Path):
    ctx = build_dynamic_context("2026-01-01T00:00:00", "chris", workspace)
    assert "Current time: 2026-01-01T00:00:00" in ctx
    assert "Talking to: @chris" in ctx


def test_build_dynamic_context_missing_profile_instruction(workspace: Path):
    ctx = build_dynamic_context("2026-01-01T00:00:00", "chris", workspace)
    assert "don't have a profile for @chris" in ctx
    assert "people/chris/profile.md" in ctx
    assert "create_link" in ctx


def test_build_dynamic_context_with_person_profile(workspace: Path):
    people = workspace / "people" / "chris"
    people.mkdir(parents=True)
    (people / "profile.md").write_text("# Chris\nLikes coffee")
    ctx = build_dynamic_context("2026-01-01T00:00:00", "chris", workspace)
    assert "## What I know about @chris" in ctx
    assert "Likes coffee" in ctx
    assert "don't have a profile" not in ctx


def test_build_dynamic_context_includes_room_context(workspace: Path):
    ctx = build_dynamic_context(
        "2026-01-01T00:00:00",
        "chris",
        workspace,
        room_context="Room: DM with @alice",
    )
    assert "Room: DM with @alice" in ctx


def test_build_dynamic_context_skips_empty_room_context(workspace: Path):
    ctx = build_dynamic_context(
        "2026-01-01T00:00:00", "chris", workspace, room_context=""
    )
    assert "Room:" not in ctx


def test_build_system_blocks_calls_prompt_providers(workspace: Path):
    (workspace / "SOUL.md").write_text("Soul.")

    def fake_provider(ws: Path) -> list[SystemBlock]:
        return [SystemBlock(text=f"Skills from {ws.name}")]

    with patch("docketeer.prompt._prompt_providers", [fake_provider]):
        blocks = build_system_blocks(workspace)

    texts = [b.text for b in blocks]
    assert any("Skills from" in t for t in texts)


def test_build_system_blocks_provider_error_is_swallowed(workspace: Path):
    (workspace / "SOUL.md").write_text("Soul.")

    def bad_provider(ws: Path) -> list[SystemBlock]:
        raise RuntimeError("boom")

    with patch("docketeer.prompt._prompt_providers", [bad_provider]):
        blocks = build_system_blocks(workspace)

    assert len(blocks) >= 1


def test_build_system_blocks_provider_blocks_after_stable(
    workspace: Path,
):
    (workspace / "SOUL.md").write_text("Soul.")

    def provider(ws: Path) -> list[SystemBlock]:
        return [SystemBlock(text="plugin-content")]

    with patch("docketeer.prompt._prompt_providers", [provider]):
        blocks = build_system_blocks(workspace)

    assert blocks[0].text == "Soul."
    assert blocks[1].text == "plugin-content"
    assert blocks[-1].cache_control == CacheControl()


def test_system_block_to_dict():
    block = SystemBlock(text="hello")
    assert block.to_dict() == {"type": "text", "text": "hello"}


def test_system_block_to_dict_with_cache_control():
    block = SystemBlock(text="hello", cache_control=CacheControl())
    api_dict = block.to_dict()
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


# --- format_message_time ---


def test_format_message_time_absolute_without_previous():
    ts = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    result = format_message_time(ts)
    assert "2026-02-06" in result
    assert "10:00" in result or "05:00" in result  # depends on local tz


def test_format_message_time_seconds():
    t1 = datetime(2026, 2, 6, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 6, 10, 0, 30, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+30s"


def test_format_message_time_minutes():
    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 6, 10, 5, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+5m"


def test_format_message_time_hours_and_minutes():
    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 6, 12, 15, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+2h 15m"


def test_format_message_time_days_and_hours():
    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 7, 13, 0, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+1d 3h"


def test_format_message_time_days_only():
    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 9, 10, 0, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+3d"


@pytest.mark.parametrize(
    ("delta_seconds", "expected"),
    [
        (0, "+0s"),
        (1, "+1s"),
        (59, "+59s"),
        (60, "+1m"),
        (90, "+1m 30s"),
        (3_600, "+1h"),
        (3_661, "+1h 1m"),
        (86_400, "+1d"),
        (90_061, "+1d 1h"),
    ],
)
def test_format_message_time_parametrized(delta_seconds: int, expected: str):
    from datetime import timedelta

    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=delta_seconds)
    assert format_message_time(t2, t1) == expected


def test_format_message_time_negative_clamped():
    t1 = datetime(2026, 2, 6, 10, 5, tzinfo=UTC)
    t2 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+0s"


def test_format_message_time_two_unit_max():
    t1 = datetime(2026, 2, 6, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 7, 11, 15, 30, tzinfo=UTC)
    result = format_message_time(t2, t1)
    assert result == "+1d 1h"


def test_message_param_to_dict_str_content():
    msg = MessageParam(role="user", content="hello")
    assert msg.to_dict() == {"role": "user", "content": "hello"}


def test_message_param_to_dict_list_with_to_dict():
    from docketeer.prompt import TextBlockParam

    msg = MessageParam(role="user", content=[TextBlockParam(text="hello")])
    result = msg.to_dict()
    assert result["role"] == "user"
    assert result["content"] == [{"type": "text", "text": "hello"}]


def test_message_param_to_dict_list_with_dict():
    msg = MessageParam(role="user", content=[{"type": "text", "text": "hello"}])
    result = msg.to_dict()
    assert result["role"] == "user"
    assert result["content"] == [{"type": "text", "text": "hello"}]


def test_message_param_to_dict_list_with_other():
    msg = MessageParam(role="user", content=["plain string"])
    result = msg.to_dict()
    assert result["role"] == "user"
    assert result["content"] == [{"type": "text", "text": "plain string"}]


def test_message_param_to_dict_list_with_model_dump():
    """Test that objects with model_dump() but not to_dict() are handled."""

    class ModelWithDump:
        def model_dump(self) -> dict[str, str]:
            return {"type": "custom", "value": "test"}

    msg = MessageParam(role="user", content=[ModelWithDump()])
    result = msg.to_dict()
    assert result["role"] == "user"
    assert result["content"] == [{"type": "custom", "value": "test"}]


def test_message_param_to_dict_list_with_anthropic_block():
    """Test that anthropic blocks (which have to_dict) are handled."""
    from anthropic.types import TextBlock

    block = TextBlock(type="text", text="from anthropic")
    msg = MessageParam(role="user", content=[block])
    result = msg.to_dict()
    assert result["role"] == "user"
    assert result["content"] == [{"type": "text", "text": "from anthropic"}]


def test_text_block_param_to_dict():
    from docketeer.prompt import TextBlockParam

    block = TextBlockParam(text="hello")
    assert block.to_dict() == {"type": "text", "text": "hello"}


def test_image_block_param_to_dict():
    from docketeer.prompt import Base64ImageSourceParam, ImageBlockParam

    source = Base64ImageSourceParam(media_type="image/png", data="abc123")
    block = ImageBlockParam(source=source)
    result = block.to_dict()
    assert result == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "abc123"},
    }


def test_base64_image_source_param_to_dict():
    from docketeer.prompt import Base64ImageSourceParam

    source = Base64ImageSourceParam(media_type="image/jpeg", data="xyz789")
    result = source.to_dict()
    assert result == {"type": "base64", "media_type": "image/jpeg", "data": "xyz789"}


def test_message_param_to_dict_fallback():
    msg = MessageParam(role="user", content=b"bytes")  # type: ignore[arg-type]
    result = msg.to_dict()
    assert result == {"role": "user", "content": b"bytes"}
