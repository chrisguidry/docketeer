"""Sandboxed command execution tools."""

from pathlib import Path

from docketeer.executor import CompletedProcess, Mount

from . import ToolContext, registry

NO_EXECUTOR = (
    "No executor available — install an executor plugin (e.g. docketeer-bubblewrap)"
)

NO_VAULT = "No vault available — secret_env requires a vault plugin"


def _sandbox_mounts(ctx: ToolContext) -> list[Mount]:
    scratch = ctx.workspace / "tmp"
    scratch.mkdir(exist_ok=True)
    return [
        Mount(source=ctx.workspace, target=Path("/workspace")),
        Mount(source=scratch, target=Path("/tmp"), writable=True),
    ]


def _format_result(result: CompletedProcess) -> str:
    parts: list[str] = []
    if result.stdout:
        parts.append(result.stdout.decode(errors="replace"))
    if result.stderr:
        parts.append(f"[stderr]\n{result.stderr.decode(errors='replace')}")
    if result.returncode != 0:
        parts.append(f"[exit code {result.returncode}]")
    return "\n".join(parts) if parts else "(no output)"


async def _resolve_secret_env(
    ctx: ToolContext, secret_env: dict[str, str]
) -> dict[str, str]:
    """Resolve secret names to values via the vault."""
    resolved = {}
    for env_var, secret_name in secret_env.items():
        resolved[env_var] = await ctx.vault.resolve(secret_name)  # type: ignore[union-attr]
    return resolved


@registry.tool(emoji=":hammer_and_wrench:")
async def run(
    ctx: ToolContext,
    args: list[str],
    network: bool = False,
    secret_env: dict[str, str] | None = None,
) -> str:
    """Run a program directly in a sandboxed environment. Your workspace is
    mounted read-only at /workspace and a scratch space is writable at /tmp.
    Write any output files to /tmp — they persist in your workspace's
    tmp/ directory.

    args: the program and its arguments (e.g. ["grep", "-r", "TODO", "/workspace"])
    network: allow network access (default: false)
    secret_env: map env var names to vault secret names (e.g. {"API_KEY": "my-api-key"})
    """
    if ctx.executor is None:
        return NO_EXECUTOR
    if secret_env and ctx.vault is None:
        return NO_VAULT

    env = await _resolve_secret_env(ctx, secret_env) if secret_env else None

    running = await ctx.executor.start(
        args,
        env=env,
        mounts=_sandbox_mounts(ctx),
        network_access=network,
        username=ctx.agent_username or None,
    )
    return _format_result(await running.wait())


@registry.tool(emoji=":hammer_and_wrench:")
async def shell(
    ctx: ToolContext,
    command: str,
    network: bool = False,
    secret_env: dict[str, str] | None = None,
) -> str:
    """Run a shell command in a sandboxed environment. Supports pipes, redirects,
    and other shell features. Your workspace is mounted read-only at /workspace
    and a scratch space is writable at /tmp. Write any output files to /tmp —
    they persist in your workspace's tmp/ directory.

    command: the shell command to run (e.g. "ls -la /workspace | grep py")
    network: allow network access (default: false)
    secret_env: map env var names to vault secret names (e.g. {"API_KEY": "my-api-key"})
    """
    if ctx.executor is None:
        return NO_EXECUTOR
    if secret_env and ctx.vault is None:
        return NO_VAULT

    env = await _resolve_secret_env(ctx, secret_env) if secret_env else None

    running = await ctx.executor.start(
        ["sh", "-c", command],
        env=env,
        mounts=_sandbox_mounts(ctx),
        network_access=network,
        username=ctx.agent_username or None,
    )
    return _format_result(await running.wait())
