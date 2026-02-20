"""Tests for the plugin-based inference backend discovery."""

from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
    InferenceBackend,
)


def test_context_too_large_is_backend_error():
    assert issubclass(ContextTooLargeError, BackendError)


def test_backend_auth_error_is_backend_error():
    assert issubclass(BackendAuthError, BackendError)


class DummyBackend(InferenceBackend):  # pragma: no cover
    """Dummy implementation for testing."""

    async def run_agentic_loop(self, *args, **kwargs):  # noqa: ANN201, ANN002, ANN003
        return "dummy"

    async def count_tokens(self, *args):  # noqa: ANN201, ANN002
        return 0

    async def utility_complete(self, prompt, **kwargs):  # noqa: ANN201, ANN001, ANN003
        return prompt


async def test_inference_backend_default_context_manager():
    """Test that InferenceBackend provides default context manager behavior."""
    async with DummyBackend() as backend:
        assert backend is not None


def test_plugin_discovery_anthropic():
    """Test that the Anthropic inference plugin can be discovered."""
    from docketeer.plugins import discover_one

    ep = discover_one("docketeer.inference", "INFERENCE")
    assert ep is not None
    assert ep.name == "anthropic"
    assert ep.value == "docketeer_anthropic:create_backend"
