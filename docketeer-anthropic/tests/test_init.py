"""Tests for the create_backend factory function."""

from unittest.mock import MagicMock, patch

import pytest
from docketeer_anthropic import create_backend


def test_create_backend_default_api():
    """create_backend returns AnthropicAPIBackend by default."""
    with patch("docketeer_anthropic.environment") as mock_env:
        mock_env.get_str.return_value = "api"
        backend = create_backend(executor=None)
        assert backend is not None
        assert hasattr(backend, "_client")


def test_create_backend_api_explicit():
    """create_backend returns AnthropicAPIBackend when ANTHROPIC_BACKEND=api."""
    with patch("docketeer_anthropic.environment") as mock_env:
        mock_env.get_str.side_effect = lambda k, d=None: {
            "ANTHROPIC_BACKEND": "api",
            "ANTHROPIC_API_KEY": "test-key",
        }.get(k, d)
        backend = create_backend(executor=None)
        assert backend is not None


def test_create_backend_claude_code():
    """create_backend returns ClaudeCodeBackend when ANTHROPIC_BACKEND=claude-code."""
    mock_executor = MagicMock()
    with patch("docketeer_anthropic.environment") as mock_env:
        mock_env.get_str.side_effect = lambda k, d=None: {
            "ANTHROPIC_BACKEND": "claude-code",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
        }.get(k, d)
        backend = create_backend(executor=mock_executor)
        assert backend is not None


def test_create_backend_claude_code_requires_executor():
    """create_backend raises ValueError if claude-code backend has no executor."""
    with patch("docketeer_anthropic.environment") as mock_env:
        mock_env.get_str.side_effect = lambda k, d=None: {
            "ANTHROPIC_BACKEND": "claude-code",
            "CLAUDE_CODE_OAUTH_TOKEN": "test-token",
        }.get(k, d)
        with pytest.raises(
            ValueError, match="claude-code backend requires an executor"
        ):
            create_backend(executor=None)


def test_create_backend_unknown_type():
    """create_backend raises ValueError for unknown backend type."""
    with patch("docketeer_anthropic.environment") as mock_env:
        mock_env.get_str.return_value = "unknown"
        with pytest.raises(ValueError, match="Unknown Anthropic backend type"):
            create_backend(executor=None)
