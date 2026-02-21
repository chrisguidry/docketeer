"""Anthropic inference backend plugin for Docketeer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from docketeer import environment
from docketeer.executor import CommandExecutor

if TYPE_CHECKING:
    from docketeer.brain.core import InferenceBackend

log = logging.getLogger(__name__)

# Tier to max tokens mapping for Anthropic
TIER_MAX_TOKENS = {
    "smart": 128_000,
    "balanced": 64_000,
    "fast": 16_000,
}


def create_backend(executor: CommandExecutor | None) -> InferenceBackend:
    """Factory function to create an Anthropic backend.

    This function is the entry point for the docketeer.inference plugin.
    It decides which specific Anthropic backend to create based on the
    DOCKETEER_ANTHROPIC_BACKEND environment variable (defaults to 'api').

    Args:
        executor: CommandExecutor instance (required for claude-code backend)

    Returns:
        An InferenceBackend implementation

    Raises:
        ValueError: If backend type is unknown or configuration is invalid
    """
    backend_type = environment.get_str("ANTHROPIC_BACKEND", "api")

    if backend_type == "api":
        from docketeer_anthropic.api_backend import AnthropicAPIBackend

        api_key = environment.get_str("ANTHROPIC_API_KEY")
        return AnthropicAPIBackend(api_key)
    elif backend_type == "claude-code":
        from docketeer_anthropic.claude_code_backend import ClaudeCodeBackend

        if executor is None:
            raise ValueError("claude-code backend requires an executor plugin")
        oauth_token = environment.get_str("CLAUDE_CODE_OAUTH_TOKEN")
        return ClaudeCodeBackend(executor=executor, oauth_token=oauth_token)
    else:
        raise ValueError(
            f"Unknown Anthropic backend type: {backend_type!r}. Expected 'api' or 'claude-code'"
        )
