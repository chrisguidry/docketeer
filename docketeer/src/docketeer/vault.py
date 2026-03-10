"""Vault ABC and supporting types for secrets management."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from docketeer.plugins import PluginUnavailable, discover_one

log = logging.getLogger(__name__)

_UNAVAILABLE = "No vault plugin installed — install docketeer-1password"


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


class NullVault(Vault):
    """Falsy stand-in when no vault plugin is installed.

    Every method raises PluginUnavailable.  The falsy __bool__ lets
    callers branch on ``if vault:`` when they need to.
    """

    def __bool__(self) -> bool:
        return False

    async def list_secrets(self) -> list[SecretReference]:
        raise PluginUnavailable(_UNAVAILABLE)

    async def resolve(self, name: str) -> str:
        raise PluginUnavailable(_UNAVAILABLE)

    async def store(self, name: str, value: str) -> None:
        raise PluginUnavailable(_UNAVAILABLE)

    async def generate(self, name: str, length: int = 32) -> None:
        raise PluginUnavailable(_UNAVAILABLE)

    async def delete(self, name: str) -> None:
        raise PluginUnavailable(_UNAVAILABLE)


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
            except PluginUnavailable:
                raise
            except Exception:
                raise SecretResolutionError(
                    f"Could not resolve secret '{value.secret}' for ${key}"
                )
        else:
            resolved[key] = value
    return resolved


# --- Vault tools ---


def _register_vault_tools() -> None:
    """Register vault tools. Called lazily to avoid circular imports with tools.py."""
    from pathlib import Path

    from docketeer.executor import Mount
    from docketeer.tools import ToolContext, registry

    @registry.tool(emoji=":lock:")
    async def list_secrets(ctx: ToolContext) -> str:
        """List available secrets by name. Values are never shown."""
        refs = await ctx.vault.list_secrets()
        if not refs:
            return "No secrets available."
        return "\n".join(r.name for r in refs)

    @registry.tool(emoji=":lock:")
    async def store_secret(ctx: ToolContext, name: str, value: str) -> str:
        """Store a secret value in the vault.

        name: the secret name (e.g. "my-api-key")
        value: the secret value to store
        """
        await ctx.vault.store(name, value)
        return f"Stored secret '{name}'."

    @registry.tool(emoji=":lock:")
    async def generate_secret(ctx: ToolContext, name: str, length: int = 32) -> str:
        """Generate a random secret and store it in the vault. The value is never returned.

        name: the secret name (e.g. "db-password")
        length: number of characters (default 32)
        """
        if length < 1:
            return "length must be at least 1"

        await ctx.vault.generate(name, length)
        return f"Generated secret '{name}' ({length} chars)."

    @registry.tool(emoji=":lock:")
    async def delete_secret(ctx: ToolContext, name: str) -> str:
        """Delete a secret from the vault.

        name: the secret name to delete
        """
        await ctx.vault.delete(name)
        return f"Deleted secret '{name}'."

    @registry.tool(emoji=":lock:")
    async def capture_secret(
        ctx: ToolContext, name: str, command: str, network: bool = False
    ) -> str:
        """Run a command and capture its stdout as a secret. The output is stored
        directly in the vault — you never see the value.

        name: the secret name to store the output as
        command: the shell command to run (e.g. "gh auth token")
        network: allow network access (default: false)
        """
        scratch = ctx.workspace / "tmp"
        scratch.mkdir(exist_ok=True)
        mounts = [
            Mount(source=ctx.workspace, target=Path("/workspace")),
            Mount(source=scratch, target=Path("/tmp"), writable=True),
        ]

        running = await ctx.executor.start(
            ["sh", "-c", command],
            mounts=mounts,
            network_access=network,
            username=ctx.agent_username or None,
        )
        result = await running.wait()

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            return f"Command failed (exit code {result.returncode}): {stderr}"

        value = result.stdout.decode(errors="replace").strip()
        await ctx.vault.store(name, value)
        return f"Captured secret '{name}' ({len(value)} chars)."


def discover_vault() -> Vault:
    """Discover the vault via entry_points.

    Returns NullVault when no plugin is installed, so callers always
    get a usable Vault without null checks.
    """
    ep = discover_one("docketeer.vault", "VAULT")
    if ep is None:
        log.info("No vault plugin installed — secrets management unavailable")
        return NullVault()
    module = ep.load()
    return module.create_vault()
