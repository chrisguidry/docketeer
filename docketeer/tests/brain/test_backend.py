"""Tests for the InferenceBackend abstraction and _create_backend factory."""

from unittest.mock import patch

import pytest

from docketeer.brain.backend import BackendAuthError, BackendError, ContextTooLargeError
from docketeer.brain.core import _create_backend


def test_create_backend_defaults_to_api():
    with patch("docketeer.brain.anthropic_backend.anthropic.AsyncAnthropic"):
        backend = _create_backend()
    from docketeer.brain.anthropic_backend import AnthropicAPIBackend

    assert isinstance(backend, AnthropicAPIBackend)


def test_create_backend_explicit_api():
    with (
        patch("docketeer.brain.core.environment.get_str", side_effect=["api", ""]),
        patch("docketeer.brain.anthropic_backend.anthropic.AsyncAnthropic"),
    ):
        backend = _create_backend()
    from docketeer.brain.anthropic_backend import AnthropicAPIBackend

    assert isinstance(backend, AnthropicAPIBackend)


def test_create_backend_claude_code_raises():
    with (
        patch(
            "docketeer.brain.core.environment.get_str",
            side_effect=["claude-code"],
        ),
        pytest.raises(NotImplementedError, match="claude-code"),
    ):
        _create_backend()


def test_create_backend_unknown_raises():
    with (
        patch("docketeer.brain.core.environment.get_str", side_effect=["bogus"]),
        pytest.raises(ValueError, match="bogus"),
    ):
        _create_backend()


def test_context_too_large_is_backend_error():
    assert issubclass(ContextTooLargeError, BackendError)


def test_backend_auth_error_is_backend_error():
    assert issubclass(BackendAuthError, BackendError)
