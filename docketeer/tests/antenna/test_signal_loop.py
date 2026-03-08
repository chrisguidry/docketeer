"""Tests for the signal loop — batching, delivery, and formatting."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from docketeer.antenna import Signal, SignalFilter, Tuning
from docketeer.signal_loop import (
    deliver_batch,
    format_signal_batch,
    run_tuning,
)
from docketeer.testing import MemoryBand


def _make_signal(
    signal_id: str = "s1",
    topic: str = "events.push",
    payload: dict | None = None,
    summary: str = "A push event",
) -> Signal:
    return Signal(
        band="test",
        signal_id=signal_id,
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        topic=topic,
        payload=payload or {"action": "created"},
        summary=summary,
    )


def test_format_signal_batch_single():
    tuning = Tuning(name="github", band="wicket", topic="events")
    signals = [_make_signal()]
    result = format_signal_batch(tuning, signals)
    assert "1 signal(s)" in result
    assert "github" in result
    assert "A push event" in result
    assert "action: created" in result


def test_format_signal_batch_multiple():
    tuning = Tuning(name="github", band="wicket", topic="events")
    signals = [_make_signal(signal_id="s1"), _make_signal(signal_id="s2")]
    result = format_signal_batch(tuning, signals)
    assert "2 signal(s)" in result


def test_format_signal_batch_truncates_long_values():
    tuning = Tuning(name="t", band="b", topic="x")
    signals = [_make_signal(payload={"content": "x" * 300})]
    result = format_signal_batch(tuning, signals)
    assert "..." in result
    assert len(result) < 500


def test_format_signal_batch_uses_topic_when_no_summary():
    tuning = Tuning(name="t", band="b", topic="x")
    signals = [_make_signal(summary="")]
    result = format_signal_batch(tuning, signals)
    assert "events.push" in result


def test_format_signal_batch_empty_payload():
    tuning = Tuning(name="t", band="b", topic="x")
    signal = Signal(
        band="test",
        signal_id="s1",
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        topic="events.push",
        payload={},
        summary="empty",
    )
    result = format_signal_batch(tuning, [signal])
    assert "1 signal(s)" in result


async def test_deliver_batch_calls_process(tmp_path: Path):
    process = AsyncMock()
    tuning = Tuning(name="github", band="wicket", topic="events")
    signals = [_make_signal()]

    await deliver_batch(process, tuning, signals, tmp_path)

    process.assert_called_once()
    kwargs = process.call_args.kwargs
    assert kwargs["line"] == "github"
    assert kwargs["tier"] == "fast"
    assert "signal" in kwargs["content"].text.lower()


async def test_deliver_batch_with_purpose_prompt(tmp_path: Path):
    (tmp_path / "lines").mkdir()
    (tmp_path / "lines" / "github.md").write_text("Watch for security issues.")

    process = AsyncMock()
    tuning = Tuning(name="github", band="wicket", topic="events")
    signals = [_make_signal()]

    await deliver_batch(process, tuning, signals, tmp_path)

    kwargs = process.call_args.kwargs
    assert len(kwargs["system_context"]) == 1
    assert "security" in kwargs["system_context"][0].text


async def test_deliver_batch_no_purpose_prompt(tmp_path: Path):
    process = AsyncMock()
    tuning = Tuning(name="github", band="wicket", topic="events")
    signals = [_make_signal()]

    await deliver_batch(process, tuning, signals, tmp_path)

    kwargs = process.call_args.kwargs
    assert kwargs["system_context"] == []


async def test_deliver_batch_uses_tuning_line(tmp_path: Path):
    process = AsyncMock()
    tuning = Tuning(name="github-prs", band="wicket", topic="events", line="opensource")
    signals = [_make_signal()]

    await deliver_batch(process, tuning, signals, tmp_path)
    assert process.call_args.kwargs["line"] == "opensource"


async def test_memory_band_emit_and_listen():
    band = MemoryBand("test")
    signal = _make_signal()
    band.emit(signal)
    band.stop()

    results = []
    async for s in band.listen("t", []):
        results.append(s)
    assert len(results) == 1
    assert results[0].signal_id == "s1"


async def test_memory_band_context_manager():
    async with MemoryBand("test") as band:
        assert band.name == "test"


def test_memory_band_remote_filter_hints():
    band = MemoryBand("test")
    hints = band.remote_filter_hints([SignalFilter("x", "eq", "y")])
    assert hints == []


async def test_run_tuning_delivers_signal(tmp_path: Path):
    band = MemoryBand("test")
    tuning = Tuning(name="t", band="test", topic="events", batch_window=0.0)
    process = AsyncMock()
    signal = _make_signal()

    async with band:
        band.emit(signal)
        band.stop()

        task = asyncio.create_task(run_tuning(band, tuning, process, tmp_path))
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    process.assert_called_once()
    kwargs = process.call_args.kwargs
    assert kwargs["line"] == "t"


async def test_run_tuning_filters_signals(tmp_path: Path):
    band = MemoryBand("test")
    tuning = Tuning(
        name="t",
        band="test",
        topic="events",
        filters=[SignalFilter(path="payload.action", op="eq", value="opened")],
        batch_window=0.0,
    )
    process = AsyncMock()

    async with band:
        band.emit(_make_signal(payload={"action": "created"}))
        band.emit(_make_signal(signal_id="s2", payload={"action": "opened"}))
        band.stop()

        task = asyncio.create_task(run_tuning(band, tuning, process, tmp_path))
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert process.call_count == 1
    content_text = process.call_args.kwargs["content"].text
    assert "s2" not in content_text or "opened" in content_text


async def test_run_tuning_reconnects_on_error(tmp_path: Path):
    """When listen() raises, run_tuning logs and retries after a delay."""
    call_count = 0

    class ErrorBand(MemoryBand):
        async def listen(
            self,
            topic: str,
            filters: list[SignalFilter],
            last_signal_id: str = "",
        ) -> AsyncGenerator[Signal, None]:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("boom")
            yield  # make it a generator

    band = ErrorBand("error-band")
    tuning = Tuning(name="t", band="error-band", topic="events")
    process = AsyncMock()

    task = asyncio.create_task(
        run_tuning(band, tuning, process, tmp_path, reconnect_delay=0.01)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert call_count >= 2
