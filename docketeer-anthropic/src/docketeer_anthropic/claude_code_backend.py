"""ClaudeCodeBackend: drive `claude -p` via an executor for inference."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from docketeer import environment
from docketeer.audit import log_usage, record_usage
from docketeer.brain.backend import InferenceBackend, Usage
from docketeer.executor import ClaudeInvocation, CommandExecutor, RunningProcess
from docketeer_anthropic.claude_code_output import (
    check_process_exit,
    format_prompt,
    stream_response,
)

if TYPE_CHECKING:
    from docketeer.brain.core import InferenceModel, ProcessCallbacks
    from docketeer.brain.mcp_transport import MCPSocketServer
    from docketeer.prompt import SystemBlock
    from docketeer.tools import ToolContext, ToolDefinition

log = logging.getLogger(__name__)


@dataclass
class _Session:
    session_id: str
    message_count: int


@dataclass
class ClaudeCodeBackend(InferenceBackend):
    executor: CommandExecutor
    oauth_token: str
    claude_dir: Path = field(default_factory=lambda: environment.DATA_DIR / "claude")

    def __post_init__(self) -> None:
        self.claude_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, _Session] = {}
        self._last_context_tokens: int = -1
        self._socket_name = f"mcp-{uuid4().hex[:8]}.sock"
        self._stack: AsyncExitStack | None = None
        self._mcp_socket: MCPSocketServer | None = None
        self._mcp_socket_path: Path | None = None
        log.info("ClaudeCodeBackend initialized, claude_dir=%s", self.claude_dir)

    async def __aenter__(self) -> ClaudeCodeBackend:
        from docketeer.brain.mcp_transport import bind_mcp_socket

        socket_path = self.claude_dir / self._socket_name
        self._stack = AsyncExitStack()
        self._mcp_socket = await self._stack.enter_async_context(
            await bind_mcp_socket(socket_path)
        )
        self._mcp_socket_path = socket_path
        log.info("MCP socket bound at %s", socket_path)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack:
            await self._stack.aclose()
        self._mcp_socket = None
        self._mcp_socket_path = None

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

        session_id: str | None = None
        resume_session_id: str | None = None

        if session and len(messages) >= session.message_count:
            resume_session_id = session.session_id
            log.info(
                "Resuming session %s for room %s (messages %d >= stored %d)",
                resume_session_id,
                room_id,
                len(messages),
                session.message_count,
            )
        else:
            session_id = str(uuid4())
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
                log.info("New session %s for room %s", session_id, room_id or "(none)")

        prompt = format_prompt(messages, resume=resume_session_id is not None)
        log.info("Prompt (%d chars): %.200s", len(prompt), prompt)

        use_mcp = bool(tools and tool_context and self._mcp_socket)
        text, _, result_event = await _invoke_claude(
            self.executor,
            model.model_id,
            system_text,
            prompt,
            self.oauth_token,
            self.claude_dir,
            tool_context.workspace,
            audit_path,
            session_id=session_id,
            resume_session_id=resume_session_id,
            mcp_socket_path=self._mcp_socket_path if use_mcp else None,
            mcp_socket=self._mcp_socket if use_mcp else None,
            tool_context=tool_context if use_mcp else None,
            callbacks=callbacks,
        )

        effective_session_id = resume_session_id or session_id
        log.info(
            "Response: %d chars, session_id=%s",
            len(text),
            effective_session_id or "(none)",
        )

        if result_event:
            model_usage = result_event.get("modelUsage")
            if model_usage:
                _record_model_usage(usage_path, model_usage)
            usage = result_event.get("usage", {})
            context_tokens = (
                usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
            )
            if context_tokens:
                self._last_context_tokens = context_tokens
            cost = result_event.get("total_cost_usd")
            duration = result_event.get("duration_ms")
            api_duration = result_event.get("duration_api_ms")
            num_turns = result_event.get("num_turns")
            log.info(
                "CC metadata: cost=$%s, duration=%sms, api_duration=%sms, turns=%s",
                cost,
                duration,
                api_duration,
                num_turns,
            )

        if effective_session_id and room_id:
            self._sessions[room_id] = _Session(
                session_id=effective_session_id,
                message_count=len(messages) + 1,
            )
            log.info(
                "Stored session %s for room %s (message_count=%d)",
                effective_session_id,
                room_id,
                len(messages) + 1,
            )
        elif not effective_session_id:  # pragma: no cover
            log.warning("No session_id for room %s", room_id)
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
        return self._last_context_tokens

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
        text, _, _ = await _invoke_claude(
            self.executor,
            MODELS["haiku"].model_id,
            "You are a helpful assistant. Be concise.",
            prompt,
            self.oauth_token,
            self.claude_dir,
            scratch,
            audit,
        )
        log.info("utility_complete: response (%d chars)", len(text))
        return text


def _record_model_usage(usage_path: Path, model_usage: dict) -> None:
    """Translate CC modelUsage dicts into Usage objects and record them."""
    for model_id, data in model_usage.items():
        usage = Usage(
            input_tokens=data.get("inputTokens", 0),
            output_tokens=data.get("outputTokens", 0),
            cache_read_input_tokens=data.get("cacheReadInputTokens", 0),
            cache_creation_input_tokens=data.get("cacheCreationInputTokens", 0),
        )
        log_usage(model_id, usage)
        record_usage(usage_path, model_id, usage)


def _build_claude_args(
    model: str,
    system_text: str,
    *,
    session_id: str | None = None,
    resume_session_id: str | None = None,
) -> list[str]:
    """Build the argument list for claude -p (everything after the binary)."""
    args = [
        "-p",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--dangerously-skip-permissions",
        "--disable-slash-commands",
    ]

    if resume_session_id:
        args.extend(["--resume", resume_session_id])
    else:
        if session_id:
            args.extend(["--session-id", session_id])
        args.extend(["--system-prompt", system_text, "--model", model])

    return args


async def _invoke_claude(
    executor: CommandExecutor,
    model: str,
    system_text: str,
    prompt: str,
    oauth_token: str,
    claude_dir: Path,
    workspace: Path,
    audit_path: Path,
    *,
    session_id: str | None = None,
    resume_session_id: str | None = None,
    mcp_socket_path: Path | None = None,
    mcp_socket: MCPSocketServer | None = None,
    tool_context: ToolContext | None = None,
    callbacks: ProcessCallbacks | None = None,
) -> tuple[str, str | None, dict | None]:
    """Run claude -p via the executor and return (response_text, session_id, result_event)."""
    claude_args = _build_claude_args(
        model,
        system_text,
        session_id=session_id,
        resume_session_id=resume_session_id,
    )

    invocation = ClaudeInvocation(
        claude_args=claude_args,
        claude_dir=claude_dir,
        workspace=workspace,
        mcp_socket_path=mcp_socket_path if mcp_socket else None,
    )

    log.info(
        "Invoking claude: model=%s, session=%s, mcp=%s, "
        "system_prompt=%d chars, prompt=%d chars",
        model,
        resume_session_id or session_id or "(new)",
        "yes" if mcp_socket else "no",
        len(system_text),
        len(prompt),
    )

    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": oauth_token}
    proc = await executor.start_claude(invocation, env=env)

    log.info("claude subprocess started, pid=%s", proc.pid)

    if mcp_socket and tool_context:
        return await _invoke_claude_with_mcp(
            proc, prompt, mcp_socket, tool_context, audit_path, callbacks
        )

    return await _invoke_claude_simple(proc, prompt, callbacks)


async def _invoke_claude_simple(
    proc: RunningProcess,
    prompt: str,
    callbacks: ProcessCallbacks | None = None,
) -> tuple[str, str | None, dict | None]:
    """Run claude -p without MCP (utility calls, no tools)."""
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    stderr_task = asyncio.create_task(proc.stderr.read())
    text, session_id, result_event = await stream_response(proc.stdout, callbacks)

    stderr_bytes = await stderr_task
    await proc.wait_for_exit()
    check_process_exit(proc.returncode, stderr_bytes)
    return text, session_id, result_event


async def _invoke_claude_with_mcp(  # pragma: no cover — integration path
    proc: RunningProcess,
    prompt: str,
    mcp_socket: MCPSocketServer,
    tool_context: ToolContext,
    audit_path: Path,
    callbacks: ProcessCallbacks | None = None,
) -> tuple[str, str | None, dict | None]:
    """Run claude -p with an MCP server bridged over the pre-bound Unix socket."""
    from docketeer.brain.mcp_server import create_mcp_server
    from docketeer.brain.mcp_transport import accept_mcp_connection
    from docketeer.tools import registry

    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    server = create_mcp_server(registry, tool_context, audit_path=audit_path)

    # Send the prompt concurrently — claude needs stdin before it launches the
    # MCP bridge, but accept_mcp_connection blocks waiting for it to connect.
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    stderr_task = asyncio.create_task(proc.stderr.read())
    stream_task = asyncio.create_task(stream_response(proc.stdout, callbacks))

    try:
        async with accept_mcp_connection(mcp_socket) as (read_stream, write_stream):
            opts = server.create_initialization_options()
            server_task = asyncio.create_task(
                server.run(read_stream, write_stream, opts)
            )
            try:
                text, session_id, result_event = await stream_task
            finally:
                server_task.cancel()
                with suppress(asyncio.CancelledError):
                    await server_task
    except BaseException:
        if not stream_task.done():
            proc.kill()
            stream_task.cancel()
            with suppress(asyncio.CancelledError):
                await stream_task
        raise

    stderr_bytes = await stderr_task
    await proc.wait_for_exit()
    check_process_exit(proc.returncode, stderr_bytes)
    return text, session_id, result_event
