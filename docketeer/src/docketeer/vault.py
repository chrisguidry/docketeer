"""Vault ABC and supporting types for secrets management."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SecretReference:
    """A reference to a secret by name."""

    name: str


class Vault(ABC):
    """Abstract base for secrets management."""

    @abstractmethod
    async def list(self) -> list[SecretReference]: ...

    @abstractmethod
    async def resolve(self, name: str) -> str: ...

    @abstractmethod
    async def store(self, name: str, value: str) -> None: ...

    @abstractmethod
    async def generate(self, name: str, length: int = 32) -> None: ...

    @abstractmethod
    async def delete(self, name: str) -> None: ...
