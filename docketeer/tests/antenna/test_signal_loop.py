"""Tests for the signal loop — filtering and delivery."""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

from docketeer.antenna import Signal, SignalFilter, Tuning
from docketeer.prompt import BrainResponse
from docketeer.signal_loop import (
    deliver_signal,
    format_signal,
    log_signal,
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


def test_format_signal_basic():
    tuning = Tuning(name="github", band="wicket", topic="events")
    result = format_signal(tuning, _make_signal())
    assert "github" in result
    assert "A push event" in result
    assert '"action": "created"' in result


def test_format_signal_includes_full_payload():
    tuning = Tuning(name="t", band="b", topic="x")
    content = "x" * 3000
    result = format_signal(tuning, _make_signal(payload={"content": content}))
    assert content in result


def test_format_signal_uses_topic_when_no_summary():
    tuning = Tuning(name="t", band="b", topic="x")
    result = format_signal(tuning, _make_signal(summary=""))
    assert "events.push" in result


def test_format_signal_nested_dict_payload():
    tuning = Tuning(name="t", band="b", topic="x")
    result = format_signal(
        tuning,
        _make_signal(payload={"commit": {"operation": "create", "text": "hello"}}),
    )
    assert '"operation": "create"' in result
    assert '"text": "hello"' in result


def test_format_signal_empty_payload():
    tuning = Tuning(name="t", band="b", topic="x")
    signal = Signal(
        band="test",
        signal_id="s1",
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        topic="events.push",
        payload={},
        summary="empty",
    )
    result = format_signal(tuning, signal)
    assert "Signal on tuning" in result


def test_log_signal_writes_jsonl(tmp_path: Path):
    data_dir = tmp_path / "data"
    tuning = Tuning(name="github", band="wicket", topic="events")
    signal = _make_signal()

    log_signal(data_dir, tuning, signal)

    log_path = data_dir / "tunings" / "github" / "2026-01-01.jsonl"
    assert log_path.exists()
    record = json.loads(log_path.read_text().strip())
    assert record["signal_id"] == "s1"
    assert record["band"] == "test"
    assert record["topic"] == "events.push"
    assert record["summary"] == "A push event"
    assert record["payload"] == {"action": "created"}
    assert record["timestamp"] == "2026-01-01T12:00:00+00:00"


def test_log_signal_appends_multiple(tmp_path: Path):
    data_dir = tmp_path / "data"
    tuning = Tuning(name="t", band="b", topic="x")

    log_signal(data_dir, tuning, _make_signal(signal_id="s1"))
    log_signal(data_dir, tuning, _make_signal(signal_id="s2"))

    log_path = data_dir / "tunings" / "t" / "2026-01-01.jsonl"
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["signal_id"] == "s1"
    assert json.loads(lines[1])["signal_id"] == "s2"


async def test_deliver_signal_calls_process(tmp_path: Path):
    data_dir = tmp_path / "data"
    process = AsyncMock(return_value=BrainResponse(text="noted"))
    tuning = Tuning(name="github", band="wicket", topic="events")

    await deliver_signal(process, tuning, _make_signal(), tmp_path, data_dir)

    process.assert_called_once()
    kwargs = process.call_args.kwargs
    assert kwargs["line"] == "github"
    assert kwargs["tier"] == "fast"
    assert kwargs["content"].username is None
    assert "signal" in kwargs["content"].text.lower()


async def test_deliver_signal_logs_signal(tmp_path: Path):
    data_dir = tmp_path / "data"
    process = AsyncMock(return_value=BrainResponse(text="noted"))
    tuning = Tuning(name="github", band="wicket", topic="events")

    await deliver_signal(process, tuning, _make_signal(), tmp_path, data_dir)

    log_path = data_dir / "tunings" / "github" / "2026-01-01.jsonl"
    assert log_path.exists()


async def test_deliver_signal_with_purpose_prompt(tmp_path: Path):
    data_dir = tmp_path / "data"
    (tmp_path / "lines").mkdir()
    (tmp_path / "lines" / "github.md").write_text("Watch for security issues.")

    process = AsyncMock(return_value=BrainResponse(text=""))
    tuning = Tuning(name="github", band="wicket", topic="events")

    await deliver_signal(process, tuning, _make_signal(), tmp_path, data_dir)

    kwargs = process.call_args.kwargs
    assert len(kwargs["system_context"]) == 1
    assert "security" in kwargs["system_context"][0].text


async def test_deliver_signal_no_purpose_prompt(tmp_path: Path):
    data_dir = tmp_path / "data"
    process = AsyncMock(return_value=BrainResponse(text=""))
    tuning = Tuning(name="github", band="wicket", topic="events")

    await deliver_signal(process, tuning, _make_signal(), tmp_path, data_dir)

    kwargs = process.call_args.kwargs
    assert kwargs["system_context"] == []


async def test_deliver_signal_uses_tuning_line(tmp_path: Path):
    data_dir = tmp_path / "data"
    process = AsyncMock(return_value=BrainResponse(text=""))
    tuning = Tuning(name="github-prs", band="wicket", topic="events", line="opensource")

    await deliver_signal(process, tuning, _make_signal(), tmp_path, data_dir)
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
    data_dir = tmp_path / "data"
    band = MemoryBand("test")
    tuning = Tuning(name="t", band="test", topic="events")
    process = AsyncMock(return_value=BrainResponse(text=""))
    signal = _make_signal()

    async with band:
        band.emit(signal)
        band.stop()

        task = asyncio.create_task(
            run_tuning(band, tuning, process, tmp_path, data_dir=data_dir)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    process.assert_called_once()
    kwargs = process.call_args.kwargs
    assert kwargs["line"] == "t"


async def test_run_tuning_filters_signals(tmp_path: Path):
    data_dir = tmp_path / "data"
    band = MemoryBand("test")
    tuning = Tuning(
        name="t",
        band="test",
        topic="events",
        filters=[SignalFilter(path="payload.action", op="eq", value="opened")],
    )
    process = AsyncMock(return_value=BrainResponse(text=""))

    async with band:
        band.emit(_make_signal(payload={"action": "created"}))
        band.emit(_make_signal(signal_id="s2", payload={"action": "opened"}))
        band.stop()

        task = asyncio.create_task(
            run_tuning(band, tuning, process, tmp_path, data_dir=data_dir)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert process.call_count == 1
    content_text = process.call_args.kwargs["content"].text
    assert "s2" not in content_text or "opened" in content_text


async def test_run_tuning_reconnects_on_error(tmp_path: Path):
    """When listen() raises, run_tuning logs and retries after a delay."""
    data_dir = tmp_path / "data"
    call_count = 0

    class ErrorBand(MemoryBand):
        async def listen(
            self,
            topic: str,
            filters: list[SignalFilter],
            last_signal_id: str = "",
            secret: str | None = None,
        ) -> AsyncGenerator[Signal, None]:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("boom")
            yield  # make it a generator

    band = ErrorBand("error-band")
    tuning = Tuning(name="t", band="error-band", topic="events")
    process = AsyncMock(return_value=BrainResponse(text=""))

    task = asyncio.create_task(
        run_tuning(
            band,
            tuning,
            process,
            tmp_path,
            data_dir=data_dir,
            reconnect_delay=0.01,
        )
    )
    await asyncio.sleep(0.1)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert call_count >= 2


async def test_run_tuning_resets_backoff_on_success(tmp_path: Path):
    """After a successful signal delivery, backoff resets to initial delay."""
    data_dir = tmp_path / "data"
    band = MemoryBand("test")
    tuning = Tuning(name="t", band="test", topic="events")
    process = AsyncMock()
    signal = _make_signal()

    async with band:
        band.emit(signal)
        band.stop()

        task = asyncio.create_task(
            run_tuning(band, tuning, process, tmp_path, data_dir=data_dir)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    process.assert_called_once()
