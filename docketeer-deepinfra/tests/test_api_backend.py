"""Tests for DeepInfraAPIBackend."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docketeer.brain.backend import BackendAuthError, BackendError, ContextTooLargeError
from docketeer.tools import ToolContext
from docketeer_deepinfra.api_backend import DeepInfraAPIBackend


@pytest.fixture()
def mock_client() -> MagicMock:
    """Create a mock httpx client."""
    client = MagicMock()
    client.close = MagicMock()
    return client


@pytest.fixture()
def backend(mock_client: MagicMock) -> DeepInfraAPIBackend:
    """Create a DeepInfraAPIBackend with mocked client."""
    backend = DeepInfraAPIBackend.__new__(DeepInfraAPIBackend)
    backend._api_key = "test-key"
    backend._base_url = "https://api.deepinfra.com/v1/openai"
    backend._default_model = "MiniMaxAI/MiniMax-M2.5"
    backend._client = mock_client
    return backend


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    """Create a test tool context."""
    return ToolContext(workspace=tmp_path, username="test-user")


class TestInit:
    def test_init_creates_client(self) -> None:
        """__init__ creates an AsyncOpenAI client with the API key."""
        backend = DeepInfraAPIBackend(api_key="test-key")
        assert backend._client is not None
        assert backend._api_key == "test-key"
        assert backend._default_model == "MiniMaxAI/MiniMax-M2.5"


class TestContextManager:
    async def test_aenter_returns_backend(self) -> None:
        backend = DeepInfraAPIBackend(api_key="test-key")
        async with backend as b:
            assert b is backend

    async def test_aexit_closes_client(self) -> None:
        backend = DeepInfraAPIBackend(api_key="test-key")
        client = backend._client
        await backend.__aexit__(None, None, None)
        assert client.is_closed()


class TestRunAgenticLoop:
    async def test_run_agentic_loop_delegates_to_agentic_loop(
        self,
        backend: DeepInfraAPIBackend,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop delegates to agentic_loop and returns result."""
        with patch("docketeer_deepinfra.api_backend.agentic_loop") as mock_loop:
            mock_loop.return_value = "test response"
            result = await backend.run_agentic_loop(
                tier="balanced",
                system=[],
                messages=[],
                tools=[],
                tool_context=tool_context,
                audit_path=tmp_path / "audit",
                usage_path=tmp_path / "usage",
                callbacks=None,
            )
            assert result == "test response"
            mock_loop.assert_called_once()

    async def test_run_agentic_loop_resolves_tier_to_model(
        self,
        backend: DeepInfraAPIBackend,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop resolves tier to correct max_tokens."""
        with patch("docketeer_deepinfra.api_backend.agentic_loop") as mock_loop:
            mock_loop.return_value = "result"
            await backend.run_agentic_loop(
                tier="smart",
                system=[],
                messages=[],
                tools=[],
                tool_context=tool_context,
                audit_path=tmp_path / "audit",
                usage_path=tmp_path / "usage",
                callbacks=None,
            )
            # model is the second positional argument
            call_args = mock_loop.call_args
            model = call_args.args[1]
            # tier "smart" should use 128_000 max tokens
            assert model.max_output_tokens == 128_000

    async def test_run_agentic_loop_raises_auth_error(
        self,
        backend: DeepInfraAPIBackend,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop converts RateLimitError to BackendAuthError."""
        from openai import RateLimitError

        with patch("docketeer_deepinfra.api_backend.agentic_loop") as mock_loop:
            mock_loop.side_effect = RateLimitError(
                message="rate limited", response=MagicMock(), body=None
            )
            with pytest.raises(BackendAuthError):
                await backend.run_agentic_loop(
                    tier="balanced",
                    system=[],
                    messages=[],
                    tools=[],
                    tool_context=tool_context,
                    audit_path=tmp_path / "audit",
                    usage_path=tmp_path / "usage",
                    callbacks=None,
                )

    async def test_run_agentic_loop_raises_auth_error_auth(
        self,
        backend: DeepInfraAPIBackend,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop converts AuthenticationError to BackendAuthError."""
        from openai import AuthenticationError

        with patch("docketeer_deepinfra.api_backend.agentic_loop") as mock_loop:
            mock_loop.side_effect = AuthenticationError(
                message="invalid key", response=MagicMock(), body=None
            )
            with pytest.raises(BackendAuthError):
                await backend.run_agentic_loop(
                    tier="balanced",
                    system=[],
                    messages=[],
                    tools=[],
                    tool_context=tool_context,
                    audit_path=tmp_path / "audit",
                    usage_path=tmp_path / "usage",
                    callbacks=None,
                )

    async def test_run_agentic_loop_raises_context_too_large(
        self,
        backend: DeepInfraAPIBackend,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop converts 413 APIError to ContextTooLargeError."""
        from openai import APIError

        with patch("docketeer_deepinfra.api_backend.agentic_loop") as mock_loop:
            mock_loop.side_effect = APIError(
                message="payload too large", request=MagicMock(), body={"code": 413}
            )
            with pytest.raises(ContextTooLargeError):
                await backend.run_agentic_loop(
                    tier="balanced",
                    system=[],
                    messages=[],
                    tools=[],
                    tool_context=tool_context,
                    audit_path=tmp_path / "audit",
                    usage_path=tmp_path / "usage",
                    callbacks=None,
                )

    async def test_run_agentic_loop_raises_backend_error(
        self,
        backend: DeepInfraAPIBackend,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop converts other APIError to BackendError."""
        from openai import APIError

        with patch("docketeer_deepinfra.api_backend.agentic_loop") as mock_loop:
            mock_loop.side_effect = APIError(
                message="server error", request=MagicMock(), body=None
            )
            with pytest.raises(BackendError):
                await backend.run_agentic_loop(
                    tier="balanced",
                    system=[],
                    messages=[],
                    tools=[],
                    tool_context=tool_context,
                    audit_path=tmp_path / "audit",
                    usage_path=tmp_path / "usage",
                    callbacks=None,
                )


class TestCountTokens:
    async def test_count_tokens_returns_minus_one(
        self, backend: DeepInfraAPIBackend
    ) -> None:
        """count_tokens returns -1 as DeepInfra doesn't provide token counting."""
        result = await backend.count_tokens("some-model", [], [], [])
        assert result == -1


class TestUtilityComplete:
    async def test_utility_complete(self, backend: DeepInfraAPIBackend) -> None:
        """utility_complete returns the completion text."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "completion text"

        backend._client = MagicMock()
        backend._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await backend.utility_complete("prompt")
        assert result == "completion text"

    async def test_utility_complete_empty_content(
        self, backend: DeepInfraAPIBackend
    ) -> None:
        """utility_complete returns empty string when content is None."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        backend._client = MagicMock()
        backend._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await backend.utility_complete("prompt")
        assert result == ""

    async def test_utility_complete_raises_backend_error(
        self, backend: DeepInfraAPIBackend
    ) -> None:
        """utility_complete raises BackendError on APIError."""
        from openai import APIError

        backend._client = MagicMock()
        backend._client.chat.completions.create = AsyncMock(
            side_effect=APIError(message="server error", request=MagicMock(), body=None)
        )

        with pytest.raises(BackendError):
            await backend.utility_complete("prompt")
