"""ClaudeCodeBackend: drive `claude -p` via bwrap for inference."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from docketeer import environment
from docketeer.brain.backend import BackendError, InferenceBackend
from docketeer.brain.claude_code_output import extract_text, handle_claude_output
from docketeer.toolshed import _find_install_root

if TYPE_CHECKING:
    from docketeer.brain.core import InferenceModel, ProcessCallbacks
    from docketeer.brain.mcp_transport import MCPSocketServer
    from docketeer.prompt import SystemBlock
    from docketeer.tools import ToolContext, ToolDefinition

log = logging.getLogger(__name__)

SYSTEM_RO_BINDS = [
    "/usr",
    "/bin",
    "/lib",
    "/lib64",
    "/etc/ssl",
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/alternatives",
]


@dataclass
class _Session:
    session_id: str
    message_count: int


@dataclass
class ClaudeCodeBackend(InferenceBackend):
    oauth_token: str
    claude_dir: Path = field(default_factory=lambda: environment.DATA_DIR / "claude")

    def __post_init__(self) -> None:
        for binary in ("bwrap", "claude", "socat"):
            if not shutil.which(binary):
                raise BackendError(f"{binary} not found on PATH")

        claude_which = shutil.which("claude")
        assert claude_which is not None
        self._claude_binary = Path(claude_which).resolve()
        self._claude_install_root = _find_install_root(self._claude_binary)

        self.claude_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, _Session] = {}
        self._socket_name = f"mcp-{uuid4().hex[:8]}.sock"
        self._stack: AsyncExitStack | None = None
        self._mcp_socket: MCPSocketServer | None = None
        self._mcp_config: str | None = None
        log.info(
            "ClaudeCodeBackend initialized, claude_dir=%s, claude_binary=%s",
            self.claude_dir,
            self._claude_binary,
        )

    async def __aenter__(self) -> ClaudeCodeBackend:
        from docketeer.brain.mcp_transport import bind_mcp_socket

        socket_path = self.claude_dir / self._socket_name
        self._stack = AsyncExitStack()
        self._mcp_socket = await self._stack.enter_async_context(
            await bind_mcp_socket(socket_path)
        )
        sandbox_socket = str(Path.home() / ".claude" / self._socket_name)
        self._mcp_config = json.dumps(
            {
                "mcpServers": {
                    "docketeer": {
                        "command": "socat",
                        "args": ["STDIO", f"UNIX-CONNECT:{sandbox_socket}"],
                    }
                }
            }
        )
        log.info("MCP socket bound at %s", socket_path)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack:
            await self._stack.aclose()
        self._mcp_socket = None
        self._mcp_config = None

    async def run_agentic_loop(
        self,
        model: InferenceModel,
        system: list[SystemBlock],
        messages: list,
        tools: list[ToolDefinition],
        tool_context: ToolContext,
        audit_path: Path,
        usage_path: Path,
        callbacks: ProcessCallbacks | None,
        *,
        thinking: bool = False,
    ) -> str:
        system_text = "\n\n".join(block.text for block in system)
        room_id = tool_context.room_id
        session = self._sessions.get(room_id) if room_id else None

        log.info(
            "run_agentic_loop: room=%s, model=%s, messages=%d, session=%s",
            room_id or "(none)",
            model.model_id,
            len(messages),
            session.session_id if session else "(new)",
        )

        if session and len(messages) >= session.message_count:
            prompt = extract_text(messages[-1])
            session_id = session.session_id
            log.info(
                "Resuming session %s for room %s (messages %d >= stored %d)",
                session_id,
                room_id,
                len(messages),
                session.message_count,
            )
        else:
            prompt = extract_text(messages[-1])
            session_id = None
            if session and room_id:
                log.info(
                    "Compaction detected for room %s: messages %d < stored %d, "
                    "discarding session %s",
                    room_id,
                    len(messages),
                    session.message_count,
                    session.session_id,
                )
                del self._sessions[room_id]
            else:
                log.info("New session for room %s", room_id or "(none)")

        log.info("Prompt (%d chars): %.200s", len(prompt), prompt)

        text, new_session_id = await _invoke_claude(
            model.model_id,
            system_text,
            prompt,
            self.oauth_token,
            self.claude_dir,
            tool_context.workspace,
            audit_path,
            self._claude_binary,
            self._claude_install_root,
            session_id=session_id,
            tools=tools,
            tool_context=tool_context,
            mcp_socket=self._mcp_socket,
            mcp_config=self._mcp_config,
        )

        log.info(
            "Response: %d chars, session_id=%s",
            len(text),
            new_session_id or "(none)",
        )

        if new_session_id and room_id:
            self._sessions[room_id] = _Session(
                session_id=new_session_id,
                message_count=len(messages) + 1,
            )
            log.info(
                "Stored session %s for room %s (message_count=%d)",
                new_session_id,
                room_id,
                len(messages) + 1,
            )
        elif not new_session_id:  # pragma: no cover
            log.warning("No session_id returned from claude for room %s", room_id)
        elif not room_id:  # pragma: no cover
            log.info("Skipping session storage (no room_id)")

        return text

    async def count_tokens(
        self,
        model_id: str,
        system: list[SystemBlock],
        tools: list[ToolDefinition],
        messages: list,
    ) -> int:
        return -1

    async def utility_complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> str:
        from docketeer.brain.core import MODELS

        scratch = self.claude_dir / "scratch"
        scratch.mkdir(exist_ok=True)
        audit = self.claude_dir / "audit"
        audit.mkdir(exist_ok=True)

        log.info("utility_complete: prompt (%d chars): %.200s", len(prompt), prompt)
        text, _ = await _invoke_claude(
            MODELS["haiku"].model_id,
            "You are a helpful assistant. Be concise.",
            prompt,
            self.oauth_token,
            self.claude_dir,
            scratch,
            audit,
            self._claude_binary,
            self._claude_install_root,
        )
        log.info("utility_complete: response (%d chars)", len(text))
        return text


def _build_bwrap_command(
    model: str,
    system_text: str,
    prompt: str,
    claude_dir: Path,
    workspace: Path,
    claude_binary: Path,
    claude_install_root: Path,
    *,
    session_id: str | None = None,
    mcp_config: str | None = None,
) -> list[str]:
    """Build the bwrap + claude -p command."""
    uid = os.getuid()
    gid = os.getgid()
    home = Path.home()

    args = ["bwrap", "--die-with-parent"]

    for path in SYSTEM_RO_BINDS:
        if Path(path).exists():  # pragma: no branch
            args.extend(["--ro-bind", path, path])

    args.extend(["--proc", "/proc"])
    args.extend(["--dev", "/dev"])
    args.extend(["--tmpfs", "/tmp"])

    # Empty home — no host files leak into the sandbox
    args.extend(["--tmpfs", str(home)])

    args.extend(["--bind", str(claude_dir), str(home / ".claude")])

    # Mount the claude binary's install root if not already under system paths
    if not any(claude_install_root.is_relative_to(p) for p in SYSTEM_RO_BINDS):
        args.extend(["--ro-bind", str(claude_install_root), str(claude_install_root)])

    args.extend(["--ro-bind", str(workspace), str(workspace)])

    args.extend(["--uid", str(uid), "--gid", str(gid)])
    args.extend(["--chdir", str(workspace)])

    args.extend(
        [
            str(claude_binary),
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--disable-slash-commands",
        ]
    )

    if mcp_config:
        args.extend(["--mcp-config", mcp_config])
    else:
        args.extend(["--tools", ""])

    if session_id:
        args.extend(["--resume", session_id])
    else:
        args.extend(
            [
                "--system-prompt",
                system_text,
                "--model",
                model,
            ]
        )

    return args


async def _invoke_claude(
    model: str,
    system_text: str,
    prompt: str,
    oauth_token: str,
    claude_dir: Path,
    workspace: Path,
    audit_path: Path,
    claude_binary: Path,
    claude_install_root: Path,
    *,
    session_id: str | None = None,
    tools: list[ToolDefinition] | None = None,
    tool_context: ToolContext | None = None,
    mcp_socket: MCPSocketServer | None = None,
    mcp_config: str | None = None,
) -> tuple[str, str | None]:
    """Run claude -p inside bwrap and return (response_text, session_id).

    When tools, tool_context, and mcp_socket are provided, accepts a
    connection on the pre-bound MCP socket so the sandboxed claude process
    can call host-side tools via socat.
    """
    cmd = _build_bwrap_command(
        model,
        system_text,
        prompt,
        claude_dir,
        workspace,
        claude_binary,
        claude_install_root,
        session_id=session_id,
        mcp_config=mcp_config if tools and tool_context else None,
    )

    log.info(
        "Invoking claude: model=%s, session=%s, mcp=%s, "
        "system_prompt=%d chars, prompt=%d chars",
        model,
        session_id or "(new)",
        "yes" if (tools and tool_context and mcp_socket) else "no",
        len(system_text),
        len(prompt),
    )
    log.debug("Full bwrap command: %s", cmd)

    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": oauth_token}

    if tools and tool_context and mcp_socket:
        return await _invoke_claude_with_mcp(
            cmd, env, prompt, mcp_socket, tool_context, audit_path
        )

    return await _invoke_claude_simple(cmd, env, prompt)


async def _invoke_claude_simple(
    cmd: list[str],
    env: dict[str, str],
    prompt: str,
) -> tuple[str, str | None]:
    """Run claude -p without MCP (utility calls, no tools)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    log.info("claude subprocess started, pid=%s", proc.pid)
    stdout_bytes, stderr_bytes = await proc.communicate(input=prompt.encode())
    return handle_claude_output(proc, stdout_bytes, stderr_bytes)


async def _invoke_claude_with_mcp(  # pragma: no cover — integration path
    cmd: list[str],
    env: dict[str, str],
    prompt: str,
    mcp_socket: MCPSocketServer,
    tool_context: ToolContext,
    audit_path: Path,
) -> tuple[str, str | None]:
    """Run claude -p with an MCP server bridged over the pre-bound Unix socket."""
    from docketeer.brain.mcp_server import create_mcp_server
    from docketeer.brain.mcp_transport import accept_mcp_connection
    from docketeer.tools import registry

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    log.info("claude subprocess started (MCP), pid=%s", proc.pid)

    server = create_mcp_server(registry, tool_context, audit_path=audit_path)

    # Send the prompt concurrently — claude needs stdin before it launches socat,
    # but accept_mcp_connection blocks waiting for socat to connect.
    comm_task = asyncio.create_task(proc.communicate(input=prompt.encode()))

    try:
        async with accept_mcp_connection(mcp_socket) as (read_stream, write_stream):
            opts = server.create_initialization_options()
            server_task = asyncio.create_task(
                server.run(read_stream, write_stream, opts)
            )
            try:
                stdout_bytes, stderr_bytes = await comm_task
            finally:
                server_task.cancel()
                with suppress(asyncio.CancelledError):
                    await server_task
    except BaseException:
        if not comm_task.done():
            proc.kill()
            comm_task.cancel()
            with suppress(asyncio.CancelledError):
                await comm_task
        raise

    return handle_claude_output(proc, stdout_bytes, stderr_bytes)
