"""ClaudeCodeBackend: drive `claude -p` via bwrap for inference."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from docketeer import environment
from docketeer.brain.backend import (
    BackendAuthError,
    BackendError,
    ContextTooLargeError,
    InferenceBackend,
)

if TYPE_CHECKING:
    from docketeer.brain.core import InferenceModel, ProcessCallbacks
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
        if not shutil.which("bwrap"):
            raise BackendError("bwrap not found on PATH")
        if not shutil.which("claude"):
            raise BackendError("claude not found on PATH")

        self.claude_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, _Session] = {}
        log.info("ClaudeCodeBackend initialized, claude_dir=%s", self.claude_dir)

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
            prompt = _extract_text(messages[-1])
            session_id = session.session_id
            log.info(
                "Resuming session %s for room %s (messages %d >= stored %d)",
                session_id,
                room_id,
                len(messages),
                session.message_count,
            )
        else:
            prompt = _extract_text(messages[-1])
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
            session_id=session_id,
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

        log.info("utility_complete: prompt (%d chars): %.200s", len(prompt), prompt)
        text, _ = await _invoke_claude(
            MODELS["haiku"].model_id,
            "You are a helpful assistant. Be concise.",
            prompt,
            self.oauth_token,
            self.claude_dir,
        )
        log.info("utility_complete: response (%d chars)", len(text))
        return text


def _extract_text(message: dict) -> str:
    """Pull text from a message's content (string or list-of-blocks)."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _build_bwrap_command(
    model: str,
    system_text: str,
    prompt: str,
    claude_dir: Path,
    *,
    session_id: str | None = None,
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

    args.extend(["--ro-bind", str(home), str(home)])

    args.extend(["--bind", str(claude_dir), str(home / ".claude")])

    args.extend(["--uid", str(uid), "--gid", str(gid)])

    args.extend(
        [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--tools",
            "",
            "--dangerously-skip-permissions",
            "--disable-slash-commands",
        ]
    )

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
    *,
    session_id: str | None = None,
) -> tuple[str, str | None]:
    """Run claude -p inside bwrap and return (response_text, session_id)."""
    cmd = _build_bwrap_command(
        model,
        system_text,
        prompt,
        claude_dir,
        session_id=session_id,
    )

    log.info(
        "Invoking claude: model=%s, session=%s, system_prompt=%d chars, prompt=%d chars",
        model,
        session_id or "(new)",
        len(system_text),
        len(prompt),
    )
    log.debug("Full bwrap command: %s", cmd)

    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": oauth_token}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    log.info("claude subprocess started, pid=%s", proc.pid)

    stdout_bytes, stderr_bytes = await proc.communicate(input=prompt.encode())

    log.info(
        "claude subprocess exited: code=%s, stdout=%d bytes, stderr=%d bytes",
        proc.returncode,
        len(stdout_bytes),
        len(stderr_bytes),
    )

    if stderr_bytes:
        log.info("claude stderr: %s", stderr_bytes.decode(errors="replace").strip())

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace")
        _check_error(stderr_text, proc.returncode or 1)

    stdout_text = stdout_bytes.decode(errors="replace")
    lines = stdout_text.splitlines()
    log.info("Parsing %d lines of stream-json output", len(lines))
    return _parse_response(lines)


def _parse_response(lines: list[str]) -> tuple[str, str | None]:
    """Parse stream-json output from claude -p."""
    text_parts: list[str] = []
    session_id: str | None = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")

        if etype == "assistant":
            msg = event.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text:  # pragma: no branch
                        text_parts.append(text)

        elif etype == "result":  # pragma: no branch
            session_id = event.get("session_id", session_id)

    return "".join(text_parts).strip(), session_id


def _check_error(stderr: str, returncode: int) -> None:
    """Map stderr content to appropriate backend exceptions."""
    lower = stderr.lower()
    if any(word in lower for word in ("auth", "unauthorized", "token")):
        raise BackendAuthError(
            f"claude auth error (exit {returncode}): {stderr.strip()}"
        )
    if any(word in lower for word in ("context", "too large")):
        raise ContextTooLargeError(
            f"context too large (exit {returncode}): {stderr.strip()}"
        )
    raise BackendError(f"claude error (exit {returncode}): {stderr.strip()}")
