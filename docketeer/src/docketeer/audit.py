"""Tool call audit logging and API usage logging."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import anthropic

log = logging.getLogger(__name__)


def audit_log(
    audit_dir: Path, tool_name: str, args: dict, result: str, is_error: bool
) -> None:
    """Append a tool call record to today's audit log."""
    now = datetime.now(UTC)
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{now.strftime('%Y-%m-%d')}.jsonl"

    record = {
        "ts": now.isoformat(),
        "tool": tool_name,
        "args": args,
        "result_length": len(result),
        "is_error": is_error,
    }
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def record_usage(usage_dir: Path, model: str, usage: anthropic.types.Usage) -> None:
    """Append a token usage record to today's JSONL file."""
    now = datetime.now(UTC)
    usage_dir.mkdir(parents=True, exist_ok=True)
    path = usage_dir / f"{now.strftime('%Y-%m-%d')}.jsonl"

    record = {
        "ts": now.isoformat(),
        "model": model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0,
    }
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def log_usage(response: anthropic.types.Message) -> None:
    """Log token usage including cache stats."""
    u = response.usage
    cr = getattr(u, "cache_read_input_tokens", 0) or 0
    cw = getattr(u, "cache_creation_input_tokens", 0) or 0
    log.info(
        "Tokens: %d in (%d cache-read, %d cache-write, %d uncached), %d out",
        cr + cw + u.input_tokens,
        cr,
        cw,
        u.input_tokens,
        u.output_tokens,
    )
