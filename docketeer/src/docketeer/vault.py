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


def discover_vault() -> Vault | None:
    """Discover the vault via entry_points (optional)."""
    ep = discover_one("docketeer.vault", "VAULT")
    if ep is None:
        log.info("No vault plugin installed — secrets management unavailable")
        return None
    module = ep.load()
    return module.create_vault()
