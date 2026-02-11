"""Tests for model tier resolution and per-task model threading."""

from unittest.mock import patch

import pytest

from docketeer.brain import Brain
from docketeer.brain.core import (
    CHAT_MODEL,
    CONSOLIDATION_MODEL,
    MODEL_TIERS,
    REVERIE_MODEL,
    resolve_model,
)
from docketeer.brain.loop import (
    DEFAULT_MAX_TOKENS,
    MAX_TOKENS_BY_TIER,
    _max_tokens_for_model,
)
from docketeer.prompt import MessageContent

from ..conftest import FakeMessage, FakeMessages, make_text_block


def test_model_tiers_has_three_entries():
    assert set(MODEL_TIERS.keys()) == {"opus", "sonnet", "haiku"}


def test_resolve_model_opus():
    assert resolve_model("opus") == MODEL_TIERS["opus"]


def test_resolve_model_sonnet():
    assert resolve_model("sonnet") == MODEL_TIERS["sonnet"]


def test_resolve_model_haiku():
    assert resolve_model("haiku") == MODEL_TIERS["haiku"]


def test_resolve_model_unknown_raises():
    with pytest.raises(KeyError):
        resolve_model("gpt-4")


def test_default_chat_model_is_sonnet():
    assert CHAT_MODEL == "sonnet"


def test_default_reverie_model_is_sonnet():
    assert REVERIE_MODEL == "sonnet"


def test_default_consolidation_model_is_opus():
    assert CONSOLIDATION_MODEL == "opus"


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("claude-opus-4-6", MAX_TOKENS_BY_TIER["opus"]),
        ("claude-sonnet-4-5-20250929", MAX_TOKENS_BY_TIER["sonnet"]),
        ("claude-haiku-4-5-20251001", MAX_TOKENS_BY_TIER["haiku"]),
        ("some-unknown-model", DEFAULT_MAX_TOKENS),
    ],
)
def test_max_tokens_for_model(model_id: str, expected: int):
    assert _max_tokens_for_model(model_id) == expected


async def test_process_uses_chat_model_by_default(
    brain: Brain, fake_messages: FakeMessages
):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content)
    assert fake_messages.last_kwargs["model"] == resolve_model(CHAT_MODEL)


async def test_process_uses_explicit_model(brain: Brain, fake_messages: FakeMessages):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content, model="opus")
    assert fake_messages.last_kwargs["model"] == resolve_model("opus")


async def test_process_passes_model_to_count_tokens(
    brain: Brain, fake_messages: FakeMessages
):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    with patch.object(
        fake_messages, "count_tokens", wraps=fake_messages.count_tokens
    ) as spy:
        await brain.process("room1", content, model="sonnet")
        spy.assert_called_once()
        assert spy.call_args[1]["model"] == resolve_model("sonnet")
