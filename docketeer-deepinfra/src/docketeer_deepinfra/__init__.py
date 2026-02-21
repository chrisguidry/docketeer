"""DeepInfra inference backend plugin for Docketeer."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from docketeer import environment
from docketeer.executor import CommandExecutor

if TYPE_CHECKING:
    from docketeer.brain.backend import InferenceBackend

log = logging.getLogger(__name__)

DEFAULT_MODEL = "MiniMaxAI/MiniMax-M2.5"

# Tier to max tokens mapping
TIER_MAX_TOKENS = {
    "smart": 128_000,
    "balanced": 64_000,
    "fast": 16_000,
}


def create_backend(executor: CommandExecutor | None) -> InferenceBackend:
    """Factory function to create a DeepInfra backend.

    This function is the entry point for the docketeer.inference plugin.
    It creates a DeepInfra API backend.

    Configuration (environment variables):
        DEEPINFRA_API_KEY: Required. Your DeepInfra API key.
        DEEPINFRA_BASE_URL: Optional. Defaults to https://api.deepinfra.com/v1/openai
        DEEPINFRA_MODEL: Optional. Default model ID. Defaults to MiniMaxAI/MiniMax-M2.5

    Args:
        executor: CommandExecutor instance (unused for API backend)

    Returns:
        An InferenceBackend implementation

    Raises:
        KeyError: If API key is not configured
    """
    from docketeer_deepinfra.api_backend import DeepInfraAPIBackend

    api_key = environment.get_str("DEEPINFRA_API_KEY")
    base_url = environment.get_str(
        "DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"
    )
    default_model = environment.get_str("DEEPINFRA_MODEL", DEFAULT_MODEL)
    return DeepInfraAPIBackend(
        api_key=api_key, base_url=base_url, default_model=default_model
    )
