"""Vault tools for managing secrets."""

from pathlib import Path

from docketeer.executor import Mount

from . import ToolContext, registry

NO_VAULT = "No vault available — install a vault plugin (e.g. docketeer-1password)"
NO_EXECUTOR = (
    "No executor available — install an executor plugin (e.g. docketeer-bubblewrap)"
)


@registry.tool
async def list_secrets(ctx: ToolContext) -> str:
    """List available secrets by name. Values are never shown."""
    if ctx.vault is None:
        return NO_VAULT

    refs = await ctx.vault.list()
    if not refs:
        return "No secrets available."
    return "\n".join(r.name for r in refs)


@registry.tool
async def store_secret(ctx: ToolContext, name: str, value: str) -> str:
    """Store a secret value in the vault.

    name: the secret name (e.g. "my-api-key")
    value: the secret value to store
    """
    if ctx.vault is None:
        return NO_VAULT

    await ctx.vault.store(name, value)
    return f"Stored secret '{name}'."


@registry.tool
async def generate_secret(ctx: ToolContext, name: str, length: int = 32) -> str:
    """Generate a random secret and store it in the vault. The value is never returned.

    name: the secret name (e.g. "db-password")
    length: number of characters (default 32)
    """
    if ctx.vault is None:
        return NO_VAULT

    await ctx.vault.generate(name, length)
    return f"Generated secret '{name}' ({length} chars)."


@registry.tool
async def delete_secret(ctx: ToolContext, name: str) -> str:
    """Delete a secret from the vault.

    name: the secret name to delete
    """
    if ctx.vault is None:
        return NO_VAULT

    await ctx.vault.delete(name)
    return f"Deleted secret '{name}'."


@registry.tool
async def capture_secret(
    ctx: ToolContext, name: str, command: str, network: bool = False
) -> str:
    """Run a command and capture its stdout as a secret. The output is stored
    directly in the vault — you never see the value.

    name: the secret name to store the output as
    command: the shell command to run (e.g. "gh auth token")
    network: allow network access (default: false)
    """
    if ctx.vault is None:
        return NO_VAULT
    if ctx.executor is None:
        return NO_EXECUTOR

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
