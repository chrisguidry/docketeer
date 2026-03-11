"""Signal loop — one async task per tuning, filtering and delivery."""

import asyncio
import json
import logging
from pathlib import Path

from docketeer.antenna import Band, ProcessFn, Signal, Tuning, passes_filters
from docketeer.hooks import parse_frontmatter
from docketeer.prompt import MessageContent, SystemBlock

log = logging.getLogger(__name__)


def format_signal(tuning: Tuning, signal: Signal) -> str:
    """Format a signal into a human-readable message."""
    ts = signal.timestamp.isoformat(timespec="seconds")
    summary = signal.summary or signal.topic
    lines = [f"Signal on tuning '{tuning.name}'", ""]
    lines.append(f"[{ts}] {summary}")
    if signal.payload:
        payload_json = json.dumps(signal.payload, indent=2, default=str)
        lines.append("")
        lines.append(payload_json)
    lines.append("")
    return "\n".join(lines)


def log_signal(workspace: Path, tuning: Tuning, signal: Signal) -> None:
    """Append a signal record to the tuning's daily JSONL log in the workspace."""
    log_dir = workspace / "tunings" / tuning.name / "signals"
    log_dir.mkdir(parents=True, exist_ok=True)
    date_str = signal.timestamp.strftime("%Y-%m-%d")
    path = log_dir / f"{date_str}.jsonl"

    record = {
        "timestamp": signal.timestamp.isoformat(),
        "signal_id": signal.signal_id,
        "band": signal.band,
        "topic": signal.topic,
        "summary": signal.summary,
        "payload": signal.payload,
    }
    with path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")
        f.flush()


def _cursor_path(workspace: Path, tuning_name: str) -> Path:
    return workspace / "tunings" / tuning_name / "cursor"


def _load_cursor(workspace: Path, tuning_name: str) -> str:
    path = _cursor_path(workspace, tuning_name)
    if path.exists():
        return path.read_text().strip()
    return ""


def _save_cursor(workspace: Path, tuning_name: str, signal_id: str) -> None:
    path = _cursor_path(workspace, tuning_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(signal_id + "\n")


def _read_tuning_purpose(workspace: Path, tuning: Tuning) -> str:
    """Read the purpose/system_context for a tuning from its workspace file body."""
    path = workspace / "tunings" / f"{tuning.name}.md"
    if not path.exists():
        return ""
    content = path.read_text()
    _, body = parse_frontmatter(content)
    return body.strip()


async def deliver_signal(
    process_fn: ProcessFn,
    tuning: Tuning,
    signal: Signal,
    workspace: Path,
) -> None:
    """Deliver a signal to a line via brain.process."""
    log_signal(workspace, tuning, signal)

    line = tuning.target_line
    text = format_signal(tuning, signal)
    content = MessageContent(text=text)

    system_context: list[SystemBlock] = []
    purpose = _read_tuning_purpose(workspace, tuning)
    if purpose:
        system_context.append(SystemBlock(text=purpose))

    response = await process_fn(
        line=line,
        content=content,
        tier="fast",
        system_context=system_context,
    )
    log.info(
        "Delivered signal to line '%s', response: %s",
        line,
        response.text[:200] if response.text else "(no text)",
    )


async def run_tuning(
    band: Band,
    tuning: Tuning,
    process_fn: ProcessFn,
    workspace: Path,
    *,
    reconnect_delay: float = 1.0,
    max_reconnect_delay: float = 60.0,
    secrets: dict[str, str] | None = None,
) -> None:
    """Run a single tuning: listen, filter, deliver.

    Reconnects with exponential backoff (capped at max_reconnect_delay)
    on errors, resetting the delay after a successful signal delivery.
    """
    hint_filters = band.remote_filter_hints(tuning.filters)
    last_signal_id = _load_cursor(workspace, tuning.name)
    delay = reconnect_delay

    log.info(
        "Starting tuning '%s' on band '%s' (topic=%s, cursor=%s)",
        tuning.name,
        tuning.band,
        tuning.topic,
        last_signal_id or "(none)",
    )

    while True:
        try:
            async for signal in band.listen(
                tuning.topic,
                hint_filters,
                last_signal_id,
                secrets=secrets,
            ):
                if not passes_filters(tuning.filters, signal):
                    last_signal_id = signal.signal_id
                    _save_cursor(workspace, tuning.name, last_signal_id)
                    continue

                log.debug(
                    "Signal %s matched tuning '%s': %s",
                    signal.signal_id,
                    tuning.name,
                    signal.summary[:200],
                )
                last_signal_id = signal.signal_id
                _save_cursor(workspace, tuning.name, last_signal_id)
                delay = reconnect_delay
                await deliver_signal(process_fn, tuning, signal, workspace)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "Error in tuning '%s', reconnecting in %.1fs",
                tuning.name,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_reconnect_delay)
