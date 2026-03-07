"""Unsandboxed subprocess command executor."""

import asyncio
import json
import os
import shutil
from pathlib import Path

from docketeer.executor import (
    ClaudeInvocation,
    CommandExecutor,
    Mount,
    RunningProcess,
)

_MCP_BRIDGE_PATH = Path(__file__).resolve().parent / "mcp_bridge.py"


class SubprocessExecutor(CommandExecutor):
    """Runs commands as plain subprocesses with no sandboxing."""

    async def start(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        mounts: list[Mount] | None = None,
        network_access: bool = False,
        username: str | None = None,
    ) -> RunningProcess:
        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)

        cwd: Path | None = None
        if mounts:
            cwd = mounts[0].source

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
            cwd=cwd,
        )
        return RunningProcess(process)

    async def start_claude(  # pragma: no cover — integration path
        self,
        invocation: ClaudeInvocation,
        *,
        env: dict[str, str] | None = None,
    ) -> RunningProcess:
        claude_path = shutil.which("claude")
        if not claude_path:
            raise RuntimeError("claude not found on PATH")

        args: list[str] = [claude_path, "--tools", ""]

        if invocation.mcp_socket_path:
            mcp_config = json.dumps(
                {
                    "mcpServers": {
                        "docketeer": {
                            "command": "python3",
                            "args": [
                                str(_MCP_BRIDGE_PATH),
                                str(invocation.mcp_socket_path),
                            ],
                        }
                    }
                }
            )
            args.extend(["--mcp-config", mcp_config])

        args.extend(invocation.claude_args)

        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=invocation.workspace,
            limit=10 * 1024 * 1024,
        )
        return RunningProcess(process)
