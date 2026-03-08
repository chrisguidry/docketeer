"""Signal loop — one async task per tuning, filtering and delivery."""

import asyncio
import json
import logging
from pathlib import Path

from docketeer.antenna import Band, ProcessFn, Signal, Tuning, passes_filters
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
        if len(payload_json) > 2000:
            payload_json = payload_json[:1997] + "..."
        lines.append("")
        lines.append(payload_json)
    lines.append("")
    return "\n".join(lines)


def _read_line_purpose(workspace: Path, line: str) -> str:
    """Read the purpose prompt for a line, if it exists."""
    path = workspace / "lines" / f"{line}.md"
    if path.exists():
        return path.read_text().strip()
    return ""


async def deliver_signal(
    process_fn: ProcessFn,
    tuning: Tuning,
    signal: Signal,
    workspace: Path,
) -> None:
    """Deliver a signal to a line via brain.process."""
    line = tuning.target_line
    text = format_signal(tuning, signal)
    content = MessageContent(text=text)

    system_context: list[SystemBlock] = []
    purpose = _read_line_purpose(workspace, line)
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
    reconnect_delay: float = 1.0,
    max_reconnect_delay: float = 60.0,
    secret: str | None = None,
) -> None:
    """Run a single tuning: listen, filter, deliver.

    Reconnects with exponential backoff (capped at max_reconnect_delay)
    on errors, resetting the delay after a successful signal delivery.
    """
    hint_filters = band.remote_filter_hints(tuning.filters)
    last_signal_id = ""
    delay = reconnect_delay

    while True:
        try:
            async for signal in band.listen(
                tuning.topic,
                hint_filters,
                last_signal_id,
                secret=secret,
            ):
                if not passes_filters(tuning.filters, signal):
                    continue

                log.debug(
                    "Signal %s matched tuning '%s': %s",
                    signal.signal_id,
                    tuning.name,
                    signal.summary[:200],
                )
                last_signal_id = signal.signal_id
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
