"""Tests for the package initialization and factory function."""

from unittest.mock import patch

import pytest


class TestCreateBackend:
    def test_create_backend_requires_api_key(self) -> None:
        with patch("docketeer_deepinfra.environment") as mock_env:
            mock_env.get_str.side_effect = KeyError("DEEPINFRA_API_KEY")

            from docketeer_deepinfra import create_backend

            with pytest.raises(KeyError):
                create_backend(executor=None)

    def test_create_backend_with_defaults(self) -> None:
        with patch("docketeer_deepinfra.environment") as mock_env:
            mock_env.get_str.side_effect = lambda key, default=None: {
                "DEEPINFRA_API_KEY": "test-key",
                "DEEPINFRA_BASE_URL": "https://api.deepinfra.com/v1",
                "DEEPINFRA_MODEL": "meta-llama/Llama-3.3-70B-Instruct",
            }.get(key, default)

            from docketeer_deepinfra import create_backend
            from docketeer_deepinfra.api_backend import DeepInfraAPIBackend

            backend = create_backend(executor=None)
            assert isinstance(backend, DeepInfraAPIBackend)
            assert backend._api_key == "test-key"
            assert backend._base_url == "https://api.deepinfra.com/v1"
            assert backend._default_model == "meta-llama/Llama-3.3-70B-Instruct"

    def test_create_backend_with_custom_values(self) -> None:
        with patch("docketeer_deepinfra.environment") as mock_env:
            mock_env.get_str.side_effect = lambda key, default=None: {
                "DEEPINFRA_API_KEY": "custom-key",
                "DEEPINFRA_BASE_URL": "https://custom.example.com",
                "DEEPINFRA_MODEL": "custom/model",
            }.get(key, default)

            from docketeer_deepinfra import create_backend
            from docketeer_deepinfra.api_backend import DeepInfraAPIBackend

            backend = create_backend(executor=None)
            assert isinstance(backend, DeepInfraAPIBackend)
            assert backend._api_key == "custom-key"
            assert backend._base_url == "https://custom.example.com"
            assert backend._default_model == "custom/model"
