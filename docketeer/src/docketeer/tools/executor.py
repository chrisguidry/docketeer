"""Sandboxed command execution tools."""

from pathlib import Path

from docketeer.executor import CompletedProcess, Mount
from docketeer.vault import SecretEnvRef, SecretResolutionError, resolve_env

from . import ToolContext, registry

NO_EXECUTOR = (
    "No executor available — install an executor plugin (e.g. docketeer-bubblewrap)"
)

NO_VAULT = "No vault available — env secrets require a vault plugin"


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


async def _resolve_env(
    ctx: ToolContext, env: dict[str, str | SecretEnvRef]
) -> dict[str, str] | str:
    """Resolve an env dict, returning the resolved dict or an error string."""
    has_secrets = any(isinstance(v, SecretEnvRef) for v in env.values())
    if has_secrets and ctx.vault is None:
        return NO_VAULT
    try:
        return await resolve_env(env, ctx.vault)  # type: ignore[arg-type]
    except SecretResolutionError as e:
        return str(e)


@registry.tool(emoji=":hammer_and_wrench:")
async def run(
    ctx: ToolContext,
    args: list[str],
    network: bool = False,
    env: dict[str, str | dict] | None = None,
) -> str:
    """Run a program directly in a sandboxed environment. Your workspace is
    mounted read-only at /workspace and a scratch space is writable at /tmp.
    Write any output files to /tmp — they persist in your workspace's
    tmp/ directory.

    args: the program and its arguments (e.g. ["grep", "-r", "TODO", "/workspace"])
    network: allow network access (default: false)
    env: environment variables — values are either plain strings or
        {"secret": "vault/path"} objects for vault-backed secrets. Example:
        {"HOME": "/tmp", "API_KEY": {"secret": "my-api-key"}}
    """
    if ctx.executor is None:
        return NO_EXECUTOR

    resolved: dict[str, str] | None = None
    if env:
        parsed = _parse_env_param(env)
        result = await _resolve_env(ctx, parsed)
        if isinstance(result, str):
            return result
        resolved = result

    running = await ctx.executor.start(
        args,
        env=resolved,
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
    env: dict[str, str | dict] | None = None,
) -> str:
    """Run a shell command in a sandboxed environment. Supports pipes, redirects,
    and other shell features. Your workspace is mounted read-only at /workspace
    and a scratch space is writable at /tmp. Write any output files to /tmp —
    they persist in your workspace's tmp/ directory.

    command: the shell command to run (e.g. "ls -la /workspace | grep py")
    network: allow network access (default: false)
    env: environment variables — values are either plain strings or
        {"secret": "vault/path"} objects for vault-backed secrets. Example:
        {"HOME": "/tmp", "API_KEY": {"secret": "my-api-key"}}
    """
    if ctx.executor is None:
        return NO_EXECUTOR

    resolved: dict[str, str] | None = None
    if env:
        parsed = _parse_env_param(env)
        result = await _resolve_env(ctx, parsed)
        if isinstance(result, str):
            return result
        resolved = result

    running = await ctx.executor.start(
        ["sh", "-c", command],
        env=resolved,
        mounts=_sandbox_mounts(ctx),
        network_access=network,
        username=ctx.agent_username or None,
    )
    return _format_result(await running.wait())


def _parse_env_param(env: dict[str, str | dict]) -> dict[str, str | SecretEnvRef]:
    """Convert raw JSON env param values into typed SecretEnvRef objects."""
    parsed: dict[str, str | SecretEnvRef] = {}
    for key, value in env.items():
        if isinstance(value, dict) and "secret" in value:
            parsed[key] = SecretEnvRef(secret=value["secret"])
        else:
            parsed[key] = str(value)
    return parsed
