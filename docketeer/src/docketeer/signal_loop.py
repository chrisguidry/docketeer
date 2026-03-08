"""Signal loop — one async task per tuning, batching and delivery."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from docketeer.antenna import Band, Signal, Tuning, passes_filters
from docketeer.prompt import SystemBlock

log = logging.getLogger(__name__)


def format_signal_batch(tuning: Tuning, signals: list[Signal]) -> str:
    """Format a batch of signals into a human-readable message."""
    header = f"{len(signals)} signal(s) on tuning '{tuning.name}'"
    lines = [header, ""]
    for s in signals:
        ts = s.timestamp.isoformat(timespec="seconds")
        summary = s.summary or s.topic
        lines.append(f"- [{ts}] {summary}")
        if s.payload:
            for key, value in s.payload.items():
                text = str(value)
                if len(text) > 200:
                    text = text[:197] + "..."
                lines.append(f"  {key}: {text}")
        lines.append("")
    return "\n".join(lines)


def _read_line_purpose(workspace: Path, line: str) -> str:
    """Read the purpose prompt for a line, if it exists."""
    path = workspace / "lines" / f"{line}.md"
    if path.exists():
        return path.read_text().strip()
    return ""


ProcessFn = Callable[..., Coroutine[Any, Any, Any]]


async def deliver_batch(
    process_fn: ProcessFn,
    tuning: Tuning,
    signals: list[Signal],
    workspace: Path,
) -> None:
    """Deliver a batch of signals to a line via brain.process."""
    from docketeer.prompt import MessageContent

    line = tuning.target_line
    text = format_signal_batch(tuning, signals)
    content = MessageContent(username="antenna", text=text)

    system_context: list[SystemBlock] = []
    purpose = _read_line_purpose(workspace, line)
    if purpose:
        system_context.append(SystemBlock(text=purpose))

    await process_fn(
        line=line,
        content=content,
        tier="fast",
        system_context=system_context,
    )
    log.info("Delivered %d signal(s) to line '%s'", len(signals), line)


async def run_tuning(
    band: Band,
    tuning: Tuning,
    process_fn: ProcessFn,
    workspace: Path,
    reconnect_delay: float = 5.0,
) -> None:
    """Run a single tuning: listen, filter, batch, deliver."""
    hint_filters = band.remote_filter_hints(tuning.filters)
    last_signal_id = ""

    while True:
        try:
            async for signal in band.listen(tuning.topic, hint_filters, last_signal_id):
                if not passes_filters(tuning.filters, signal):
                    continue

                last_signal_id = signal.signal_id
                await deliver_batch(process_fn, tuning, [signal], workspace)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "Error in tuning '%s', reconnecting in %.1fs",
                tuning.name,
                reconnect_delay,
            )
            await asyncio.sleep(reconnect_delay)
