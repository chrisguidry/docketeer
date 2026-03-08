"""Tests for the Antenna orchestrator — lifecycle, tune/detune, task management."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.antenna import Antenna, Signal, Tuning, save_tuning
from docketeer.prompt import BrainResponse
from docketeer.testing import MemoryBand, MemoryVault


def _make_signal(signal_id: str = "s1") -> Signal:
    return Signal(
        band="test",
        signal_id=signal_id,
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        topic="events.push",
        payload={"action": "created"},
        summary="A push event",
    )


@pytest.fixture()
def process_fn() -> AsyncMock:
    return AsyncMock(return_value=BrainResponse(text=""))


@pytest.fixture()
def band() -> MemoryBand:
    return MemoryBand("test-band")


async def test_antenna_discovers_bands(tmp_path: Path, process_fn: AsyncMock):
    band = MemoryBand("test-band")

    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            assert any(b.name == "test-band" for b in antenna.list_bands())


async def test_antenna_loads_tunings_on_start(tmp_path: Path, process_fn: AsyncMock):
    save_tuning(tmp_path, Tuning(name="t1", band="test-band", topic="events"))
    band = MemoryBand("test-band")

    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            tunings = antenna.list_tunings()
            assert len(tunings) == 1
            assert tunings[0].name == "t1"


async def test_antenna_tune_adds_tuning(
    tmp_path: Path, process_fn: AsyncMock, band: MemoryBand
):
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            tuning = Tuning(name="new", band="test-band", topic="events")
            await antenna.tune(tuning)
            assert len(antenna.list_tunings()) == 1
            assert antenna.list_tunings()[0].name == "new"


async def test_antenna_tune_persists(
    tmp_path: Path, process_fn: AsyncMock, band: MemoryBand
):
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            await antenna.tune(Tuning(name="t1", band="test-band", topic="events"))

    # Tuning should be in the file after exit
    from docketeer.antenna import load_tunings

    assert len(load_tunings(tmp_path)) == 1


async def test_antenna_tune_rejects_unknown_band(tmp_path: Path, process_fn: AsyncMock):
    with patch("docketeer.antenna.discover_all", return_value=[]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            with pytest.raises(ValueError, match="no-such-band"):
                await antenna.tune(
                    Tuning(name="t1", band="no-such-band", topic="events")
                )


async def test_antenna_tune_replaces_existing(
    tmp_path: Path, process_fn: AsyncMock, band: MemoryBand
):
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            await antenna.tune(Tuning(name="t1", band="test-band", topic="old"))
            await antenna.tune(Tuning(name="t1", band="test-band", topic="new"))
            tunings = antenna.list_tunings()
            assert len(tunings) == 1
            assert tunings[0].topic == "new"


async def test_antenna_detune_removes_tuning(
    tmp_path: Path, process_fn: AsyncMock, band: MemoryBand
):
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            await antenna.tune(Tuning(name="t1", band="test-band", topic="events"))
            await antenna.detune("t1")
            assert antenna.list_tunings() == []


async def test_antenna_detune_unknown_raises(tmp_path: Path, process_fn: AsyncMock):
    with patch("docketeer.antenna.discover_all", return_value=[]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            with pytest.raises(KeyError, match="no-such"):
                await antenna.detune("no-such")


async def test_antenna_delivers_signals(
    tmp_path: Path, process_fn: AsyncMock, band: MemoryBand
):
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            await antenna.tune(Tuning(name="t1", band="test-band", topic="events"))
            band.emit(_make_signal())
            band.stop()
            await asyncio.sleep(0.05)

    process_fn.assert_called_once()
    assert process_fn.call_args.kwargs["line"] == "t1"


async def test_antenna_skips_tunings_for_missing_bands(
    tmp_path: Path, process_fn: AsyncMock
):
    save_tuning(tmp_path, Tuning(name="t1", band="missing-band", topic="events"))
    with patch("docketeer.antenna.discover_all", return_value=[]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            # Tuning is loaded but not running (no band)
            assert len(antenna.list_tunings()) == 1


async def test_antenna_cancels_tasks_on_exit(
    tmp_path: Path, process_fn: AsyncMock, band: MemoryBand
):
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            await antenna.tune(Tuning(name="t1", band="test-band", topic="events"))
            # Task should be running
            assert antenna._tasks.get("t1") is not None

    # After exit, task should be cancelled
    task = antenna._tasks.get("t1")
    assert task is None or task.cancelled() or task.done()


async def test_antenna_list_bands_empty(tmp_path: Path, process_fn: AsyncMock):
    with patch("docketeer.antenna.discover_all", return_value=[]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            assert len(antenna.list_bands()) == 0


async def test_antenna_resolves_secret_through_vault(
    tmp_path: Path, process_fn: AsyncMock, band: MemoryBand
):
    vault = MemoryVault({"my-secret": "s3cr3t-value"})

    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path, vault=vault) as antenna:
            await antenna.tune(
                Tuning(
                    name="t1",
                    band="test-band",
                    topic="events",
                    secret="my-secret",
                )
            )
            band.emit(_make_signal())
            band.stop()
            await asyncio.sleep(0.05)

    assert band.last_secret == "s3cr3t-value"
    process_fn.assert_called_once()


async def test_antenna_skips_tuning_when_secret_but_no_vault(
    tmp_path: Path, process_fn: AsyncMock, band: MemoryBand
):
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            await antenna.tune(
                Tuning(name="t1", band="test-band", topic="events", secret="my-secret")
            )
            assert "t1" not in antenna._tasks


async def test_antenna_no_secret_passes_none(
    tmp_path: Path, process_fn: AsyncMock, band: MemoryBand
):
    def factory() -> MemoryBand:
        return band

    with patch("docketeer.antenna.discover_all", return_value=[factory]):
        async with Antenna(process_fn, tmp_path, tmp_path) as antenna:
            await antenna.tune(Tuning(name="t1", band="test-band", topic="events"))
            band.emit(_make_signal())
            band.stop()
            await asyncio.sleep(0.05)

    assert band.last_secret is None
