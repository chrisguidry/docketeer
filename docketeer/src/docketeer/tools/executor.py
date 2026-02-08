"""Sandboxed command execution tools."""

from pathlib import Path

from docketeer.executor import CompletedProcess, Mount

from . import ToolContext, registry

NO_EXECUTOR = (
    "No executor available — install an executor plugin (e.g. docketeer-bubblewrap)"
)


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


@registry.tool
async def run(ctx: ToolContext, args: list[str], network: bool = False) -> str:
    """Run a program directly in a sandboxed environment. Your workspace is
    mounted read-only at /workspace and a scratch space is writable at /tmp.
    Write any output files to /tmp — they persist in your workspace's
    tmp/ directory.

    args: the program and its arguments (e.g. ["grep", "-r", "TODO", "/workspace"])
    network: allow network access (default: false)
    """
    if ctx.executor is None:
        return NO_EXECUTOR

    running = await ctx.executor.start(
        args,
        mounts=_sandbox_mounts(ctx),
        network_access=network,
        username=ctx.agent_username or None,
    )
    return _format_result(await running.wait())


@registry.tool
async def shell(ctx: ToolContext, command: str, network: bool = False) -> str:
    """Run a shell command in a sandboxed environment. Supports pipes, redirects,
    and other shell features. Your workspace is mounted read-only at /workspace
    and a scratch space is writable at /tmp. Write any output files to /tmp —
    they persist in your workspace's tmp/ directory.

    command: the shell command to run (e.g. "ls -la /workspace | grep py")
    network: allow network access (default: false)
    """
    if ctx.executor is None:
        return NO_EXECUTOR

    running = await ctx.executor.start(
        ["sh", "-c", command],
        mounts=_sandbox_mounts(ctx),
        network_access=network,
        username=ctx.agent_username or None,
    )
    return _format_result(await running.wait())
