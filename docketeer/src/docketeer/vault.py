"""Vault ABC and supporting types for secrets management."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from docketeer.plugins import discover_one

log = logging.getLogger(__name__)


@dataclass
class SecretReference:
    """A reference to a secret by name."""

    name: str


@dataclass
class SecretEnvRef:
    """A vault secret reference for use as an environment variable value."""

    secret: str


class SecretResolutionError(Exception):
    """Raised when a vault secret cannot be resolved for an env var."""


class Vault(ABC):
    """Abstract base for secrets management."""

    @abstractmethod
    async def list_secrets(self) -> list[SecretReference]: ...

    @abstractmethod
    async def resolve(self, name: str) -> str: ...

    @abstractmethod
    async def store(self, name: str, value: str) -> None: ...

    @abstractmethod
    async def generate(self, name: str, length: int = 32) -> None: ...

    @abstractmethod
    async def delete(self, name: str) -> None: ...


async def resolve_env(
    env: dict[str, str | SecretEnvRef], vault: Vault
) -> dict[str, str]:
    """Resolve an env dict containing a mix of plain strings and vault refs.

    Plain string values pass through unchanged; SecretEnvRef values are
    resolved via the vault.  Raises SecretResolutionError if any secret
    lookup fails.
    """
    resolved: dict[str, str] = {}
    for key, value in env.items():
        if isinstance(value, SecretEnvRef):
            try:
                resolved[key] = await vault.resolve(value.secret)
            except Exception:
                raise SecretResolutionError(
                    f"Could not resolve secret '{value.secret}' for ${key}"
                )
        else:
            resolved[key] = value
    return resolved


def discover_vault() -> Vault | None:
    """Discover the vault via entry_points (optional)."""
    ep = discover_one("docketeer.vault", "VAULT")
    if ep is None:
        log.info("No vault plugin installed — secrets management unavailable")
        return None
    module = ep.load()
    return module.create_vault()
