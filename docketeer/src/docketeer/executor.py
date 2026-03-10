"""CommandExecutor ABC and supporting types for sandboxed process execution."""

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from docketeer.plugins import PluginUnavailable, discover_one

log = logging.getLogger(__name__)

_UNAVAILABLE = (
    "No executor plugin installed"
    " — install docketeer-bubblewrap or docketeer-subprocess"
)


@dataclass
class Mount:
    """A filesystem mount to expose inside the sandbox."""

    source: Path
    target: Path
    writable: bool = False


@dataclass
class ClaudeInvocation:
    """Everything the executor needs to launch claude -p in a sandbox."""

    claude_args: list[str] = field(default_factory=list)
    claude_dir: Path = Path()
    workspace: Path = Path()
    mcp_socket_path: Path | None = None


@dataclass
class CompletedProcess:
    """Result of a finished subprocess."""

    returncode: int
    stdout: bytes
    stderr: bytes


class RunningProcess:
    """Wrapper around an asyncio subprocess, providing a clean interface."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process

    @property
    def pid(self) -> int | None:
        return self._process.pid

    @property
    def stdin(self) -> asyncio.StreamWriter | None:
        return self._process.stdin

    @property
    def stdout(self) -> asyncio.StreamReader | None:
        return self._process.stdout

    @property
    def stderr(self) -> asyncio.StreamReader | None:
        return self._process.stderr

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    async def wait(self) -> CompletedProcess:
        stdout, stderr = await self._process.communicate()
        return CompletedProcess(
            returncode=self._process.returncode or 0,
            stdout=stdout or b"",
            stderr=stderr or b"",
        )

    async def wait_for_exit(self) -> int:
        """Wait for the process to exit without consuming stdout/stderr.

        Use this when stdout has already been consumed (e.g. by stream_response).
        """
        await self._process.wait()
        return self._process.returncode or 0

    def terminate(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            self._process.terminate()

    def kill(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            self._process.kill()


class CommandExecutor(ABC):
    """Abstract base for sandboxed command execution."""

    remaps_paths: bool = True
    """Whether this executor remaps mount targets into a sandbox namespace.

    When True (bubblewrap), the agent sees mount targets like /workspace.
    When False (subprocess), the agent sees the real source paths.
    """

    @abstractmethod
    async def start(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        mounts: list[Mount] | None = None,
        network_access: bool = False,
        username: str | None = None,
    ) -> RunningProcess: ...

    async def start_claude(
        self,
        invocation: ClaudeInvocation,
        *,
        env: dict[str, str] | None = None,
    ) -> RunningProcess:
        raise NotImplementedError(
            f"{type(self).__name__} does not support running Claude Code"
        )


class NullExecutor(CommandExecutor):
    """Falsy stand-in when no executor plugin is installed.

    Every method raises PluginUnavailable.  The falsy __bool__ lets
    callers branch on ``if executor:`` when they need to.
    """

    def __bool__(self) -> bool:
        return False

    async def start(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        mounts: list[Mount] | None = None,
        network_access: bool = False,
        username: str | None = None,
    ) -> RunningProcess:
        raise PluginUnavailable(_UNAVAILABLE)


WORKSPACE_TARGET = Path("/workspace")
SCRATCH_TARGET = Path("/tmp")


# --- Executor tools ---


def _register_executor_tools() -> None:
    """Register executor tools. Called lazily to avoid circular imports with tools.py."""
    from docketeer.tools import ToolContext, registry
    from docketeer.vault import SecretEnvRef, SecretResolutionError, resolve_env

    def _sandbox_mounts(ctx: ToolContext) -> list[Mount]:
        scratch = ctx.workspace / "tmp"
        scratch.mkdir(exist_ok=True)
        return [
            Mount(source=ctx.workspace, target=WORKSPACE_TARGET),
            Mount(source=scratch, target=SCRATCH_TARGET, writable=True),
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
        try:
            return await resolve_env(env, ctx.vault)
        except SecretResolutionError as e:
            return str(e)

    def _parse_env_param(
        env: dict[str, str | dict],
    ) -> dict[str, str | SecretEnvRef]:
        parsed: dict[str, str | SecretEnvRef] = {}
        for key, value in env.items():
            if isinstance(value, dict) and "secret" in value:
                parsed[key] = SecretEnvRef(secret=value["secret"])
            else:
                parsed[key] = str(value)
        return parsed

    @registry.tool(emoji=":hammer_and_wrench:")
    async def run(
        ctx: ToolContext,
        args: list[str],
        network: bool = False,
        env: dict[str, str | dict] | None = None,
    ) -> str:
        """Run a program directly in a sandboxed environment. Your workspace is
        mounted read-only at {workspace} and a scratch space is writable at
        {scratch}. Write any output files to {scratch} — they persist in your
        workspace's tmp/ directory.

        args: the program and its arguments (e.g. ["grep", "-r", "TODO", "{workspace}"])
        network: allow network access (default: false)
        env: environment variables — values are either plain strings or
            {{"secret": "vault/path"}} objects for vault-backed secrets. Example:
            {{"HOME": "/tmp", "API_KEY": {{"secret": "my-api-key"}}}}
        """
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
        and other shell features. Your workspace is mounted read-only at {workspace}
        and a scratch space is writable at {scratch}. Write any output files to
        {scratch} — they persist in your workspace's tmp/ directory.

        command: the shell command to run (e.g. "ls -la {workspace} | grep py")
        network: allow network access (default: false)
        env: environment variables — values are either plain strings or
            {{"secret": "vault/path"}} objects for vault-backed secrets. Example:
            {{"HOME": "/tmp", "API_KEY": {{"secret": "my-api-key"}}}}
        """
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


def discover_executor() -> CommandExecutor:
    """Discover the command executor via entry_points.

    Returns NullExecutor when no plugin is installed, so callers always
    get a usable CommandExecutor without null checks.
    """
    ep = discover_one("docketeer.executor", "EXECUTOR")
    if ep is None:
        log.info("No executor plugin installed — sandboxed execution unavailable")
        return NullExecutor()
    module = ep.load()
    return module.create_executor()
