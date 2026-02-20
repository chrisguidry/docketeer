"""Tests for AnthropicAPIBackend."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from anthropic import APIError, AuthenticationError
from anthropic._exceptions import PermissionDeniedError, RequestTooLargeError
from anthropic.types import TextBlock
from docketeer_anthropic.api_backend import AnthropicAPIBackend

from docketeer.brain.backend import BackendAuthError, BackendError, ContextTooLargeError
from docketeer.brain.core import InferenceModel
from docketeer.prompt import CacheControl, MessageParam, SystemBlock
from docketeer.tools import ToolContext

MODEL = InferenceModel(model_id="claude-sonnet-4-5-20251001", max_output_tokens=64_000)


@pytest.fixture()
def mock_client() -> MagicMock:
    """Create a mock Anthropic client."""
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.stream = MagicMock()
    client.messages.count_tokens = AsyncMock()
    client.messages.create = AsyncMock()
    return client


@pytest.fixture()
def backend(mock_client: MagicMock, tmp_path: Path) -> AnthropicAPIBackend:
    """Create an AnthropicAPIBackend with mocked client."""
    backend = AnthropicAPIBackend.__new__(AnthropicAPIBackend)
    backend._client = mock_client
    return backend


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:
    """Create a test tool context."""
    return ToolContext(workspace=tmp_path, username="test-user")


class FakeStream:  # pragma: no cover
    """Fake stream context manager for testing."""

    def __init__(self, response: MagicMock) -> None:
        self._response = response
        self.text_stream = self._make_text_stream()

    def _make_text_stream(self) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for block in self._response.content:
                if hasattr(block, "text"):
                    yield block.text[:5] if len(block.text) > 5 else block.text

        return gen()

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    async def get_final_message(self) -> MagicMock:
        return self._response


def make_response(
    content: Any, stop_reason: str = "end_turn", usage: Any = None
) -> MagicMock:
    """Create a mock response."""
    response = MagicMock()
    response.content = content if isinstance(content, list) else [content]
    response.stop_reason = stop_reason
    response.usage = usage or MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return response


class TestAnthropicAPIBackendInit:
    def test_init_creates_client(self) -> None:
        """__init__ creates an AsyncAnthropic client with the API key."""
        backend = AnthropicAPIBackend(api_key="test-key")
        assert backend._client is not None


class TestRunAgenticLoop:
    async def test_run_agentic_loop_success(
        self,
        backend: AnthropicAPIBackend,
        mock_client: MagicMock,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop delegates to agentic_loop and returns result."""
        text_block = MagicMock(spec=TextBlock)
        text_block.text = "Hello!"
        response = make_response([text_block])

        fake_stream = FakeStream(response)
        mock_client.messages.stream.return_value = fake_stream

        with patch("docketeer_anthropic.api_backend.agentic_loop") as mock_loop:
            mock_loop.return_value = "result"
            result = await backend.run_agentic_loop(
                model=MODEL,
                system=[],
                messages=[],
                tools=[],
                tool_context=tool_context,
                audit_path=tmp_path / "audit",
                usage_path=tmp_path / "usage",
                callbacks=None,
            )
            assert result == "result"
            mock_loop.assert_called_once()

    async def test_run_agentic_loop_raises_context_too_large(
        self,
        backend: AnthropicAPIBackend,
        mock_client: MagicMock,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop converts RequestTooLargeError to ContextTooLargeError."""
        from docketeer_anthropic import api_backend

        with patch.object(api_backend, "agentic_loop") as mock_loop:
            mock_loop.side_effect = RequestTooLargeError(
                "too large", response=MagicMock(), body=None
            )
            with pytest.raises(ContextTooLargeError):
                await backend.run_agentic_loop(
                    model=MODEL,
                    system=[],
                    messages=[],
                    tools=[],
                    tool_context=tool_context,
                    audit_path=tmp_path / "audit",
                    usage_path=tmp_path / "usage",
                    callbacks=None,
                )

    async def test_run_agentic_loop_raises_backend_auth_error_on_auth(
        self,
        backend: AnthropicAPIBackend,
        mock_client: MagicMock,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop converts AuthenticationError to BackendAuthError."""
        from docketeer_anthropic import api_backend

        with patch.object(api_backend, "agentic_loop") as mock_loop:
            mock_loop.side_effect = AuthenticationError(
                "invalid key", response=MagicMock(), body=None
            )
            with pytest.raises(BackendAuthError):
                await backend.run_agentic_loop(
                    model=MODEL,
                    system=[],
                    messages=[],
                    tools=[],
                    tool_context=tool_context,
                    audit_path=tmp_path / "audit",
                    usage_path=tmp_path / "usage",
                    callbacks=None,
                )

    async def test_run_agentic_loop_raises_backend_auth_error_on_permission(
        self,
        backend: AnthropicAPIBackend,
        mock_client: MagicMock,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop converts PermissionDeniedError to BackendAuthError."""
        from docketeer_anthropic import api_backend

        with patch.object(api_backend, "agentic_loop") as mock_loop:
            mock_loop.side_effect = PermissionDeniedError(
                "denied", response=MagicMock(), body=None
            )
            with pytest.raises(BackendAuthError):
                await backend.run_agentic_loop(
                    model=MODEL,
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
        backend: AnthropicAPIBackend,
        mock_client: MagicMock,
        tool_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        """run_agentic_loop converts APIError to BackendError."""
        from docketeer_anthropic import api_backend

        _FAKE_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

        with patch.object(api_backend, "agentic_loop") as mock_loop:
            mock_loop.side_effect = APIError("api error", _FAKE_REQUEST, body=None)
            with pytest.raises(BackendError):
                await backend.run_agentic_loop(
                    model=MODEL,
                    system=[],
                    messages=[],
                    tools=[],
                    tool_context=tool_context,
                    audit_path=tmp_path / "audit",
                    usage_path=tmp_path / "usage",
                    callbacks=None,
                )


class TestCountTokens:
    async def test_count_tokens_success(
        self, backend: AnthropicAPIBackend, mock_client: MagicMock
    ) -> None:
        """count_tokens returns token count from API."""
        mock_result = MagicMock()
        mock_result.input_tokens = 42
        mock_client.messages.count_tokens.return_value = mock_result

        system = [SystemBlock(text="system")]
        tools: list[Any] = []
        messages = [{"role": "user", "content": "hello"}]

        result = await backend.count_tokens("model-id", system, tools, messages)
        assert result == 42
        mock_client.messages.count_tokens.assert_called_once()

    async def test_count_tokens_serializes_messageparam(
        self, backend: AnthropicAPIBackend, mock_client: MagicMock
    ) -> None:
        """count_tokens serializes MessageParam objects."""
        mock_result = MagicMock()
        mock_result.input_tokens = 10
        mock_client.messages.count_tokens.return_value = mock_result

        messages = [MessageParam(role="user", content="hello")]
        result = await backend.count_tokens("model-id", [], [], messages)
        assert result == 10

    async def test_count_tokens_api_error_returns_minus_one(
        self, backend: AnthropicAPIBackend, mock_client: MagicMock
    ) -> None:
        """count_tokens returns -1 on API error."""
        _FAKE_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

        mock_client.messages.count_tokens.side_effect = APIError(
            "error", _FAKE_REQUEST, body=None
        )

        result = await backend.count_tokens("model-id", [], [], [])
        assert result == -1


class TestUtilityComplete:
    async def test_utility_complete_success(
        self, backend: AnthropicAPIBackend, mock_client: MagicMock
    ) -> None:
        """utility_complete returns text from response."""
        text_block = MagicMock(spec=TextBlock)
        text_block.text = "Hello!"
        response = MagicMock()
        response.content = [text_block]
        mock_client.messages.create.return_value = response

        result = await backend.utility_complete("prompt")
        assert result == "Hello!"
        mock_client.messages.create.assert_called_once()

    async def test_utility_complete_non_text_block(
        self, backend: AnthropicAPIBackend, mock_client: MagicMock
    ) -> None:
        """utility_complete handles non-text blocks."""
        non_text = MagicMock()
        non_text.text = None
        response = MagicMock()
        response.content = [non_text]
        mock_client.messages.create.return_value = response

        result = await backend.utility_complete("prompt")
        assert result is not None

    async def test_utility_complete_api_error(
        self, backend: AnthropicAPIBackend, mock_client: MagicMock
    ) -> None:
        """utility_complete raises BackendError on API error."""
        _FAKE_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        mock_client.messages.create.side_effect = APIError(
            "error", _FAKE_REQUEST, body=None
        )

        with pytest.raises(BackendError):
            await backend.utility_complete("prompt")


class TestSystemToDict:
    def test_system_to_dict_without_cache_control(
        self, backend: AnthropicAPIBackend
    ) -> None:
        """_system_to_dict serializes SystemBlock without cache control."""
        block = SystemBlock(text="hello")
        result = backend._system_to_dict(block)
        assert result == {"type": "text", "text": "hello"}

    def test_system_to_dict_with_cache_control(
        self, backend: AnthropicAPIBackend
    ) -> None:
        """_system_to_dict serializes SystemBlock with cache control."""
        block = SystemBlock(text="hello", cache_control=CacheControl(ttl="1h"))
        result = backend._system_to_dict(block)
        assert result == {
            "type": "text",
            "text": "hello",
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }


class TestToolToDict:
    def test_tool_to_dict_with_to_api_dict(self, backend: AnthropicAPIBackend) -> None:
        """_tool_to_dict uses to_api_dict."""
        tool = MagicMock()
        tool.to_api_dict.return_value = {"name": "test", "input_schema": {}}
        result = backend._tool_to_dict(tool)
        tool.to_api_dict.assert_called_once()
        assert result == {"name": "test", "input_schema": {}}

    def test_tool_to_dict_fallback_on_attribute_error(
        self, backend: AnthropicAPIBackend
    ) -> None:
        """_tool_to_dict falls back when to_api_dict raises AttributeError."""
        tool = MagicMock()
        tool.to_api_dict.side_effect = AttributeError("no to_api_dict")
        tool.name = "test"
        tool.input_schema = {"type": "object"}
        result = backend._tool_to_dict(tool)
        assert result == {"name": "test", "input_schema": {"type": "object"}}
