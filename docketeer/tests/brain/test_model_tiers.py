"""Tests for model tier resolution and per-task model threading."""

from unittest.mock import patch

import pytest

from docketeer.brain import Brain
from docketeer.brain.core import (
    CHAT_MODEL,
    CONSOLIDATION_MODEL,
    MODELS,
    REVERIE_MODEL,
    InferenceModel,
    resolve_model,
)
from docketeer.prompt import MessageContent

from ..conftest import FakeMessage, FakeMessages, make_text_block


def test_models_has_three_entries():
    assert set(MODELS.keys()) == {"opus", "sonnet", "haiku"}


def test_models_values_are_inference_models():
    for model in MODELS.values():
        assert isinstance(model, InferenceModel)


def test_resolve_model_opus():
    assert resolve_model("opus") is MODELS["opus"]


def test_resolve_model_sonnet():
    assert resolve_model("sonnet") is MODELS["sonnet"]


def test_resolve_model_haiku():
    assert resolve_model("haiku") is MODELS["haiku"]


def test_resolve_model_unknown_raises():
    with pytest.raises(KeyError):
        resolve_model("gpt-4")


def test_default_chat_model_is_opus():
    assert CHAT_MODEL == "opus"


def test_default_reverie_model_is_opus():
    assert REVERIE_MODEL == "opus"


def test_default_consolidation_model_is_opus():
    assert CONSOLIDATION_MODEL == "opus"


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        ("opus", 128_000),
        ("sonnet", 64_000),
        ("haiku", 16_000),
    ],
)
def test_max_output_tokens(tier: str, expected: int):
    assert MODELS[tier].max_output_tokens == expected


def test_sonnet_has_thinking_budget():
    assert MODELS["sonnet"].thinking_budget == 10_000


def test_opus_has_no_thinking_budget():
    assert MODELS["opus"].thinking_budget is None


def test_haiku_has_no_thinking_budget():
    assert MODELS["haiku"].thinking_budget is None


async def test_process_uses_chat_model_by_default(
    brain: Brain, fake_messages: FakeMessages
):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content)
    assert fake_messages.last_kwargs["model"] == MODELS[CHAT_MODEL].model_id


async def test_process_uses_explicit_model(brain: Brain, fake_messages: FakeMessages):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content, model="opus")
    assert fake_messages.last_kwargs["model"] == MODELS["opus"].model_id


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
        assert spy.call_args[1]["model"] == MODELS["sonnet"].model_id


async def test_thinking_enabled_for_sonnet_when_requested(
    brain: Brain, fake_messages: FakeMessages
):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content, model="sonnet", thinking=True)
    assert fake_messages.last_kwargs["thinking"] == {
        "type": "enabled",
        "budget_tokens": 10_000,
    }


async def test_thinking_not_sent_without_flag(
    brain: Brain, fake_messages: FakeMessages
):
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Hi!")])]
    content = MessageContent(username="chris", text="hello")
    await brain.process("room1", content, model="sonnet", thinking=False)
    from anthropic import omit

    assert fake_messages.last_kwargs["thinking"] is omit
